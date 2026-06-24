from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.agents.base import AgentState, BaseAgent
from app.core.config import settings
from app.models.models import (
    BusinessProfile, Contract, Document, DocumentStatus, Employee,
    Exception as Ex, ExceptionQueue, ExceptionSeverity, ExceptionStatus,
    GRN, LeaseContract, ProcessingStage, PurchaseOrder, ValidationProfile,
    ValidationResult, ValidationRule, ValidationStatus
)
from app.tools.audit_tool import log_audit, update_workflow_stage


class ProfileValidationAgent(BaseAgent):
    """
    Agent 7: PROFILE VALIDATION
    Applies profile-specific rules from the database.
    Falls back to hardcoded rules if DB rules not loaded.
    """

    name = "PROFILE_VALIDATION_AGENT"
    progress_on_entry = 70
    progress_on_exit = 78

    def _execute(self, state: AgentState) -> AgentState:
        document_id: str = state["document_id"]
        business_profile: str = state.get("business_profile", "")
        extracted: Dict[str, Any] = state.get("extracted_data", {}) or {}

        doc = self.db.query(Document).filter(Document.id == document_id).first()

        # Load DB-driven rules for this profile
        db_profile = self.db.query(ValidationProfile).filter(
            ValidationProfile.business_profile == business_profile,
            ValidationProfile.is_active == True,
        ).first()

        validation_results: List[Tuple] = []

        if db_profile:
            validation_results = self._run_db_rules(db_profile, doc, extracted)
        else:
            validation_results = self._run_builtin_rules(business_profile, doc, extracted)

        fail_count = 0
        critical_fails = []
        for rule_code, rule_name, status, expected, actual, reason, severity, rule_id in validation_results:
            vr = ValidationResult(
                document_id=document_id,
                rule_id=rule_id,
                rule_code=rule_code,
                rule_name=rule_name,
                status=status,
                expected_value=str(expected) if expected is not None else None,
                actual_value=str(actual) if actual is not None else None,
                reason=reason,
                severity=severity,
                agent=self.name,
            )
            self.db.add(vr)
            if status == ValidationStatus.FAIL and severity == "FAIL":
                fail_count += 1
                critical_fails.append(rule_code)

        self.db.flush()

        log_audit(
            self.db,
            document_id=document_id,
            entity_type="DOCUMENT",
            action="PROFILE_VALIDATION_COMPLETE",
            agent=self.name,
            after_state={
                "business_profile": business_profile,
                "total_rules": len(validation_results),
                "fail_count": fail_count,
                "critical_fails": critical_fails,
            },
            stage=ProcessingStage.PROFILE_VALIDATION,
        )

        if critical_fails:
            self._create_exception(doc, critical_fails, business_profile)

        needs_po_matching = business_profile in {
            BusinessProfile.PO_RAW_MATERIAL,
            BusinessProfile.PO_CAPEX,
            BusinessProfile.PO_OPEX,
        }

        next_agent = "MATCHING_AGENT" if needs_po_matching else "APPROVAL_AGENT"
        next_stage = ProcessingStage.MATCHING if needs_po_matching else ProcessingStage.APPROVAL

        update_workflow_stage(
            self.db,
            document_id=document_id,
            stage=next_stage,
            agent=self.name,
            progress_percent=78,
        )

        state["profile_validation_fails"] = fail_count
        state["needs_po_matching"] = needs_po_matching
        state.set_status("SUCCESS")
        state.set_next_agent(next_agent)
        return state

    def _run_db_rules(self, profile: ValidationProfile, doc: Document, extracted: Dict) -> List[Tuple]:
        results = []
        for rule in profile.rules:
            if not rule.is_active:
                continue
            status, expected, actual, reason = self._evaluate_rule(rule, doc, extracted)
            results.append((rule.rule_code, rule.rule_name, status, expected, actual, reason, rule.severity, rule.id))
        return results

    def _evaluate_rule(self, rule: ValidationRule, doc: Document, extracted: Dict) -> Tuple:
        params = rule.parameters or {}
        rule_type = rule.rule_type

        if rule_type == "EXISTENCE":
            field = params.get("field", "")
            value = self._get_field(extracted, field) or getattr(doc, field.split(".")[-1], None)
            # references.po_number / references.grn_number may be resolved
            # server-side (BusinessProfileAgent's open-PO / GRN lookup) without
            # ever being printed on the invoice — doc.po_id / doc.grn_id is the
            # source of truth for "is this PO/GRN-backed", not the raw text.
            if not value and field == "references.po_number" and doc.po_id:
                value = doc.po_id
            if not value and field == "references.grn_number" and doc.grn_id:
                value = doc.grn_id
            if value:
                return ValidationStatus.PASS, "Non-null", value, f"{field} present"
            return ValidationStatus.FAIL, "Non-null", None, f"{field} is missing"

        if rule_type == "REGEX":
            field = params.get("field", "")
            pattern = params.get("pattern", "")
            import re
            value = str(self._get_field(extracted, field) or "")
            if re.match(pattern, value):
                return ValidationStatus.PASS, pattern, value, "Pattern matched"
            return ValidationStatus.FAIL, pattern, value, f"Pattern {pattern} not matched"

        if rule_type == "RANGE":
            field = params.get("field", "")
            min_val = params.get("min")
            max_val = params.get("max")
            value = self._get_field(extracted, field)
            try:
                num = float(str(value or 0))
                if min_val is not None and num < float(min_val):
                    return ValidationStatus.FAIL, f">= {min_val}", value, f"{field} {num} < {min_val}"
                if max_val is not None and num > float(max_val):
                    return ValidationStatus.FAIL, f"<= {max_val}", value, f"{field} {num} > {max_val}"
                return ValidationStatus.PASS, f"{min_val}-{max_val}", value, f"{field} in range"
            except Exception:
                return ValidationStatus.WARNING, f"{min_val}-{max_val}", value, f"Cannot evaluate range for {field}"

        return ValidationStatus.SKIPPED, None, None, f"Rule type {rule_type} not implemented"

    def _run_builtin_rules(self, profile: str, doc: Document, extracted: Dict) -> List[Tuple]:
        refs = extracted.get("references") or {}
        results = []

        if profile == BusinessProfile.PO_RAW_MATERIAL:
            results.extend(self._validate_po_raw_material(doc, extracted, refs))
        elif profile == BusinessProfile.NON_PO_RAW_MATERIAL:
            results.extend(self._validate_non_po(doc, extracted))
        elif profile == BusinessProfile.PO_CAPEX:
            results.extend(self._validate_po_capex(doc, extracted, refs))
        elif profile == BusinessProfile.NON_PO_CAPEX:
            results.extend(self._validate_non_po_capex(doc, extracted))
        elif profile in (BusinessProfile.PO_OPEX, BusinessProfile.NON_PO_OPEX):
            results.extend(self._validate_opex(doc, extracted, refs, has_po=(profile == BusinessProfile.PO_OPEX)))
        elif profile == BusinessProfile.LEASE_RENT:
            results.extend(self._validate_lease(doc, extracted, refs))
        elif profile == BusinessProfile.EMPLOYEE_REIMBURSEMENT:
            results.extend(self._validate_reimbursement(doc, extracted))
        elif profile == BusinessProfile.PETTY_CASH:
            results.extend(self._validate_petty_cash(doc, extracted))

        return results

    def _validate_po_raw_material(self, doc: Document, extracted: Dict, refs: Dict) -> List[Tuple]:
        results = []
        po_number = refs.get("po_number")
        rule_id = None

        if not po_number and not doc.po_id:
            results.append(("PO_MANDATORY", "PO Number Present", ValidationStatus.FAIL, "Non-null PO", None, "PO number required for PO_RAW_MATERIAL", "FAIL", rule_id))
        else:
            po = None
            if doc.po_id:
                po = self.db.query(PurchaseOrder).filter(PurchaseOrder.id == doc.po_id).first()
            if po:
                if po.status not in ("OPEN", "PARTIALLY_RECEIVED"):
                    results.append(("PO_OPEN", "PO Status Open", ValidationStatus.FAIL, "OPEN or PARTIALLY_RECEIVED", po.status, f"PO {po.po_number} is {po.status}", "FAIL", rule_id))
                else:
                    results.append(("PO_OPEN", "PO Status Open", ValidationStatus.PASS, "OPEN", po.status, f"PO {po.po_number} is open", "FAIL", rule_id))
                if po.vendor_id and doc.vendor_id and str(po.vendor_id) != str(doc.vendor_id):
                    results.append(("PO_VENDOR_MATCH", "PO Vendor Match", ValidationStatus.FAIL, "Vendor matches PO", "Mismatch", "Invoice vendor does not match PO vendor", "FAIL", rule_id))
                else:
                    results.append(("PO_VENDOR_MATCH", "PO Vendor Match", ValidationStatus.PASS, "Match", "Match", "Vendor matches PO", "FAIL", rule_id))
            else:
                results.append(("PO_EXISTS", "PO Exists in System", ValidationStatus.FAIL, "PO found in DB", po_number, f"PO {po_number} not found in system", "FAIL", rule_id))

        if not refs.get("grn_number") and not doc.grn_id:
            results.append(("GRN_MANDATORY", "GRN Reference Present", ValidationStatus.FAIL, "Non-null GRN", None, "GRN required for PO_RAW_MATERIAL", "FAIL", rule_id))
        else:
            results.append(("GRN_MANDATORY", "GRN Reference Present", ValidationStatus.PASS, "Non-null GRN", refs.get("grn_number"), "GRN reference present", "FAIL", rule_id))

        return results

    def _validate_non_po(self, doc: Document, extracted: Dict) -> List[Tuple]:
        rule_id = None
        vendor_data = extracted.get("vendor") or {}
        results = [
            ("VENDOR_NAME", "Vendor Name Present", ValidationStatus.PASS if vendor_data.get("name") else ValidationStatus.FAIL, "Non-null", vendor_data.get("name"), "Vendor name check", "FAIL", rule_id),
        ]
        return results

    def _validate_po_capex(self, doc: Document, extracted: Dict, refs: Dict) -> List[Tuple]:
        rule_id = None
        results = list(self._validate_po_raw_material(doc, extracted, refs))
        asset_tag = refs.get("asset_tag")
        results.append(("ASSET_TAG", "Asset Tag Present", ValidationStatus.PASS if asset_tag else ValidationStatus.WARNING, "Non-null asset tag", asset_tag, "Asset tag validation", "WARNING", rule_id))
        return results

    def _validate_non_po_capex(self, doc: Document, extracted: Dict) -> List[Tuple]:
        rule_id = None
        refs = extracted.get("references") or {}
        asset_tag = refs.get("asset_tag") or refs.get("asset_serial")
        results = [
            ("ASSET_REFERENCE", "Asset Reference Present", ValidationStatus.PASS if asset_tag else ValidationStatus.FAIL, "Non-null", asset_tag, "Asset reference for CAPEX", "FAIL", rule_id),
        ]
        return results

    def _validate_opex(self, doc: Document, extracted: Dict, refs: Dict, has_po: bool) -> List[Tuple]:
        rule_id = None
        results = []
        if has_po and not refs.get("po_number") and not doc.po_id:
            results.append(("PO_MANDATORY", "PO Number Present", ValidationStatus.FAIL, "Non-null PO", None, "PO required for PO_OPEX", "FAIL", rule_id))
        lease = extracted.get("lease") or {}
        if lease.get("billing_period"):
            results.append(("BILLING_PERIOD", "Billing Period Present", ValidationStatus.PASS, "Non-null", lease.get("billing_period"), "Billing period present", "FAIL", rule_id))
        return results

    def _validate_lease(self, doc: Document, extracted: Dict, refs: Dict) -> List[Tuple]:
        rule_id = None
        results = []
        contract_number = refs.get("lease_contract_number") or refs.get("contract_number")
        if contract_number:
            contract = self.db.query(LeaseContract).filter(LeaseContract.contract_number == contract_number).first()
            if not contract:
                results.append(("LEASE_CONTRACT_EXISTS", "Lease Contract Found", ValidationStatus.FAIL, "Contract in DB", contract_number, f"Lease contract {contract_number} not found — LEASE_CONTRACT_NOT_FOUND", "FAIL", rule_id))
            else:
                results.append(("LEASE_CONTRACT_EXISTS", "Lease Contract Found", ValidationStatus.PASS, "Contract in DB", contract_number, "Lease contract found", "FAIL", rule_id))
                vendor_data = extracted.get("vendor") or {}
                lease_data = extracted.get("lease") or {}
                amounts = extracted.get("amounts") or {}
                claimed_rent = float(str(amounts.get("subtotal") or amounts.get("total_amount") or 0).replace(",", "") or 0)
                contract_rent = float(contract.monthly_rent or 0)
                if claimed_rent > 0 and contract_rent > 0:
                    variance = abs(claimed_rent - contract_rent) / contract_rent * 100
                    if variance > 5:
                        results.append(("RENT_AMOUNT_MATCH", "Rent Amount Match", ValidationStatus.FAIL, str(contract_rent), str(claimed_rent), f"Rent variance {variance:.1f}% > 5%", "FAIL", rule_id))
                    else:
                        results.append(("RENT_AMOUNT_MATCH", "Rent Amount Match", ValidationStatus.PASS, str(contract_rent), str(claimed_rent), "Rent within tolerance", "FAIL", rule_id))
        else:
            results.append(("LEASE_CONTRACT_PRESENT", "Lease Contract Reference", ValidationStatus.FAIL, "Non-null contract ref", None, "LEASE_CONTRACT_NOT_FOUND: No lease contract reference in document", "FAIL", rule_id))
        return results

    def _validate_reimbursement(self, doc: Document, extracted: Dict) -> List[Tuple]:
        rule_id = None
        emp_data = extracted.get("employee_reimbursement") or {}
        refs = extracted.get("references") or {}
        results = []
        emp_code = refs.get("employee_code") or emp_data.get("employee_code")
        if not emp_code and not doc.employee_id:
            results.append(("EMPLOYEE_EXISTS", "Employee Reference", ValidationStatus.FAIL, "Employee code or link", None, "No employee reference found", "FAIL", rule_id))
        else:
            emp = None
            if doc.employee_id:
                emp = self.db.query(Employee).filter(Employee.id == doc.employee_id).first()
            elif emp_code:
                emp = self.db.query(Employee).filter(Employee.employee_code == emp_code).first()
            if emp:
                results.append(("EMPLOYEE_EXISTS", "Employee Reference", ValidationStatus.PASS, "Employee in DB", emp_code, f"Employee {emp.name} found", "FAIL", rule_id))
                amounts = extracted.get("amounts") or {}
                claimed = float(str(amounts.get("total_amount") or 0).replace(",", "") or 0)
                if claimed > float(emp.monthly_reimbursement_limit or 0):
                    results.append(("REIMBURSEMENT_LIMIT", "Reimbursement Within Limit", ValidationStatus.FAIL, str(emp.monthly_reimbursement_limit), str(claimed), f"Amount {claimed} exceeds limit {emp.monthly_reimbursement_limit}", "FAIL", rule_id))
                else:
                    results.append(("REIMBURSEMENT_LIMIT", "Reimbursement Within Limit", ValidationStatus.PASS, str(emp.monthly_reimbursement_limit), str(claimed), "Within policy limit", "FAIL", rule_id))
            else:
                results.append(("EMPLOYEE_EXISTS", "Employee Reference", ValidationStatus.FAIL, "Employee in DB", emp_code, f"Employee {emp_code} not found", "FAIL", rule_id))
        return results

    def _validate_petty_cash(self, doc: Document, extracted: Dict) -> List[Tuple]:
        rule_id = None
        amounts = extracted.get("amounts") or {}
        total = float(str(amounts.get("total_amount") or 0).replace(",", "") or 0)
        petty = extracted.get("petty_cash") or {}
        results = [
            ("PETTY_CASH_LIMIT", "Petty Cash Limit", ValidationStatus.PASS if total <= 5000 else ValidationStatus.FAIL, "<= 5000", total, f"Amount {total}", "FAIL", rule_id),
            ("PETTY_RECEIPT", "Receipt Present", ValidationStatus.PASS if petty.get("expense_category") else ValidationStatus.WARNING, "Category", petty.get("expense_category"), "Expense category check", "WARNING", rule_id),
        ]
        return results

    def _create_exception(self, doc: Document, fail_codes: List[str], profile: str) -> None:
        ex = Ex(
            document_id=doc.id,
            exception_code="PROFILE_VALIDATION_FAIL",
            exception_type="VALIDATION_FAILURE",
            severity=ExceptionSeverity.HIGH,
            queue=ExceptionQueue.AP_TEAM,
            title=f"Profile validation failed: {profile}",
            description=f"Failed rules: {', '.join(fail_codes)}",
            agent_raised_by=self.name,
            status=ExceptionStatus.OPEN,
            sla_hours=settings.SLA_AP_TEAM_HOURS,
        )
        self.db.add(ex)
        self.db.flush()

    @staticmethod
    def _get_field(extracted: Dict, field: str) -> Any:
        parts = field.split(".")
        current = extracted
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current