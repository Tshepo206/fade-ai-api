from bank_reconciliation import SmartBankReconciliationManager


class ReconciliationManager:
    @staticmethod
    def reconcile_statement(business_id: str, filename: str, file_bytes: bytes, period: str = "month") -> dict:
        return SmartBankReconciliationManager.reconcile_statement(business_id, filename, file_bytes, period)
