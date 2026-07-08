import csv
import io
import re
from datetime import datetime
from typing import List, Dict

from pypdf import PdfReader

from db_manager import BarberDatabaseManager


class SmartBankReconciliationManager:
    @staticmethod
    def reconcile_statement(filename: str, file_bytes: bytes, period: str = "month") -> dict:
        bank_transactions = SmartBankReconciliationManager._parse_file(
            filename=filename,
            file_bytes=file_bytes,
        )

        ledger_transactions = BarberDatabaseManager.get_recent_transactions(limit=500)

        matches = []
        unmatched_bank = []
        unmatched_ledger = []

        used_ledger_indexes = set()

        for bank_tx in bank_transactions:
            match_index = None

            for index, ledger_tx in enumerate(ledger_transactions):
                if index in used_ledger_indexes:
                    continue

                if SmartBankReconciliationManager._is_match(bank_tx, ledger_tx):
                    match_index = index
                    break

            if match_index is not None:
                used_ledger_indexes.add(match_index)

                matches.append(
                    {
                        "status": "Matched",
                        "bank_transaction": bank_tx,
                        "ledger_transaction": SmartBankReconciliationManager._clean_ledger_transaction(
                            ledger_transactions[match_index]
                        ),
                    }
                )
            else:
                unmatched_bank.append(
                    {
                        "status": "Missing from Fade books",
                        "bank_transaction": bank_tx,
                        "suggested_action": "Review this bank transaction and add it to Fade if it is business income or expense.",
                    }
                )

        for index, ledger_tx in enumerate(ledger_transactions):
            if index not in used_ledger_indexes:
                clean_tx = SmartBankReconciliationManager._clean_ledger_transaction(ledger_tx)

                if clean_tx["payment_method"] == "Cash":
                    continue

                unmatched_ledger.append(
                    {
                        "status": "Missing from bank statement",
                        "ledger_transaction": clean_tx,
                        "suggested_action": "Check if this card transaction appears on another bank statement or date.",
                    }
                )

        total_bank_amount = sum(float(item.get("amount") or 0) for item in bank_transactions)
        total_matched_amount = sum(
            float(item["bank_transaction"].get("amount") or 0) for item in matches
        )

        match_rate = round((len(matches) / len(bank_transactions)) * 100) if bank_transactions else 0

        return {
            "success": True,
            "period": period,
            "bank_transactions_count": len(bank_transactions),
            "ledger_transactions_checked": len(ledger_transactions),
            "matched_count": len(matches),
            "unmatched_bank_count": len(unmatched_bank),
            "unmatched_ledger_count": len(unmatched_ledger),
            "match_rate": match_rate,
            "total_bank_amount": total_bank_amount,
            "total_matched_amount": total_matched_amount,
            "matches": matches,
            "unmatched_bank": unmatched_bank,
            "unmatched_ledger": unmatched_ledger,
        }

    @staticmethod
    def _parse_file(filename: str, file_bytes: bytes) -> List[Dict]:
        lower_name = filename.lower()

        if lower_name.endswith(".csv"):
            return SmartBankReconciliationManager._parse_csv(file_bytes)

        if lower_name.endswith(".pdf"):
            return SmartBankReconciliationManager._parse_pdf(file_bytes)

        raise ValueError("Unsupported file type. Please upload CSV or PDF.")

    @staticmethod
    def _parse_csv(file_bytes: bytes) -> List[Dict]:
        decoded = file_bytes.decode("utf-8-sig", errors="ignore")
        reader = csv.DictReader(io.StringIO(decoded))

        transactions = []

        for row in reader:
            date_value = SmartBankReconciliationManager._find_value(
                row, ["date", "transaction date", "posting date"]
            )

            description = SmartBankReconciliationManager._find_value(
                row, ["description", "details", "reference", "narrative"]
            )

            amount_value = SmartBankReconciliationManager._find_value(
                row, ["amount", "value", "credit", "debit"]
            )

            amount = SmartBankReconciliationManager._parse_amount(amount_value)

            if amount == 0:
                continue

            transactions.append(
                {
                    "date": date_value,
                    "description": description or "Bank transaction",
                    "amount": abs(amount),
                    "raw_amount": amount,
                }
            )

        return transactions

    @staticmethod
    def _parse_pdf(file_bytes: bytes) -> List[Dict]:
        pdf_stream = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_stream)

        text_parts = []

        for page in reader.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)

        full_text = "\n".join(text_parts)
        lines = full_text.splitlines()

        transactions = []

        amount_pattern = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d{2})|[-+]?\d+\.\d{2}")

        for line in lines:
            amounts = amount_pattern.findall(line)

            if not amounts:
                continue

            amount = SmartBankReconciliationManager._parse_amount(amounts[-1])

            if amount == 0:
                continue

            transactions.append(
                {
                    "date": "",
                    "description": line.strip()[:180],
                    "amount": abs(amount),
                    "raw_amount": amount,
                }
            )

        return transactions

    @staticmethod
    def _find_value(row: dict, possible_names: list):
        normalized = {str(k).strip().lower(): v for k, v in row.items()}

        for name in possible_names:
            if name in normalized:
                return normalized[name]

        return None

    @staticmethod
    def _parse_amount(value) -> float:
        if value is None:
            return 0

        clean = str(value)
        clean = clean.replace("R", "")
        clean = clean.replace(",", "")
        clean = clean.replace(" ", "")
        clean = clean.strip()

        if clean in ["", "-", "None", "none"]:
            return 0

        try:
            return float(clean)
        except ValueError:
            return 0

    @staticmethod
    def _is_match(bank_tx: dict, ledger_tx: dict) -> bool:
        bank_amount = round(float(bank_tx.get("amount") or 0), 2)

        ledger_credit = round(float(ledger_tx.get("credit_amount") or 0), 2)
        ledger_debit = round(float(ledger_tx.get("debit_amount") or 0), 2)
        ledger_amount = ledger_credit if ledger_credit > 0 else ledger_debit

        payment_method = (ledger_tx.get("payment_method") or "").strip().title()

        if payment_method == "Cash":
            return False

        return bank_amount == round(ledger_amount, 2)

    @staticmethod
    def _clean_ledger_transaction(row: dict) -> dict:
        credit = float(row.get("credit_amount") or 0)
        debit = float(row.get("debit_amount") or 0)

        return {
            "transaction_timestamp": row.get("transaction_timestamp"),
            "amount": credit if credit > 0 else debit,
            "account_type": row.get("account_type"),
            "narrative": row.get("narrative"),
            "customer_name": row.get("customer_name"),
            "service_name": row.get("service_name"),
            "payment_method": row.get("payment_method"),
        }