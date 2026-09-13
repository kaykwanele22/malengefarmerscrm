import importlib
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path


class FinanceLedgerRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_ledger_test_")
        cls.db_path = Path(cls.tempdir.name) / "ledger.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{cls.db_path.as_posix()}"
        os.environ["SECRET_KEY"] = "ledger-regression-secret"
        os.environ["APP_ENV"] = "development"
        os.environ["TWO_FACTOR_REQUIRED"] = "false"
        os.environ["DOCUMENT_UPLOAD_DIR"] = str(Path(cls.tempdir.name) / "documents")

        cls.crm = importlib.import_module("app")
        cls.ledger = importlib.import_module("account_ledger")
        cls.p7 = importlib.import_module("phase7")
        cls.crm.app.config.update(TESTING=True, TWO_FACTOR_REQUIRED=False)

        with cls.crm.app.app_context():
            cls.crm.db.create_all()
            cls._seed()

    @classmethod
    def _seed(cls):
        c = cls.crm
        coop_a = c.Cooperative(name="Ledger Siyaphumla", cooperative_type="Primary", code="LGA", status="Active")
        coop_b = c.Cooperative(name="Ledger Vimba", cooperative_type="Primary", code="LGB", status="Active")
        c.db.session.add_all([coop_a, coop_b])
        c.db.session.flush()
        cls.coop_a, cls.coop_b = coop_a.id, coop_b.id

        cls.users = {}
        for key, role, coop in [
            ("treasurer", "Primary Treasurer", coop_a.id),
            ("chair", "Primary Chairperson", coop_a.id),
            ("other_chair", "Primary Chairperson", coop_b.id),
        ]:
            user = c.User(
                fullname=key.replace("_", " ").title(),
                phone=f"07123{len(cls.users):05d}",
                email=f"{key}@ledger.local",
                farm_location="Malenge",
                password=c.generate_password_hash("Testing123!"),
            )
            c.db.session.add(user)
            c.db.session.flush()
            c.db.session.add(c.UserAccess(user_id=user.id, cooperative_id=coop, role=role, status="Active"))
            cls.users[key] = user.id

        farmer_a = c.Farmer(cooperative_id=coop_a.id, fullname="Farmer A", phone="0711111111", location="A", status="Active")
        farmer_b = c.Farmer(cooperative_id=coop_b.id, fullname="Farmer B", phone="0722222222", location="B", status="Active")
        c.db.session.add_all([farmer_a, farmer_b])
        c.db.session.flush()
        contribution_a = c.Contribution(
            cooperative_id=coop_a.id,
            farmer_id=farmer_a.id,
            amount=300,
            contribution_date=c.crm_today(),
            category="Membership Fee",
            method="Cash",
            reference="LEDGER-A-001",
            status="Confirmed",
        )
        contribution_b = c.Contribution(
            cooperative_id=coop_b.id,
            farmer_id=farmer_b.id,
            amount=300,
            contribution_date=c.crm_today(),
            category="Membership Fee",
            method="Cash",
            reference="LEDGER-B-001",
            status="Confirmed",
        )
        c.db.session.add_all([contribution_a, contribution_b])
        c.db.session.commit()
        cls.source_a, cls.source_b = contribution_a.id, contribution_b.id

    @classmethod
    def tearDownClass(cls):
        with cls.crm.app.app_context():
            cls.crm.db.session.remove()
            cls.crm.db.drop_all()
            cls.crm.db.engine.dispose()
        cls.tempdir.cleanup()

    def setUp(self):
        self.client = self.crm.app.test_client()
        c, l, p = self.crm, self.ledger, self.p7
        with c.app.app_context():
            l.LedgerTransactionRevision.query.delete()
            l.FinanceReconciliation.query.delete()
            l.LedgerTransaction.query.delete()
            l.FinanceAccount.query.delete()
            p.CooperativeDocument.query.delete()
            c.db.session.commit()

    def login_as(self, key):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["user_id"] = self.users[key]
            sess["fullname"] = key.title()

    def _create_confirmed_income(self):
        c, l = self.crm, self.ledger
        self.login_as("treasurer")
        response = self.client.post("/finance/accounts", data={
            "name": "Co-op Bank", "account_type": "Bank Account", "institution": "Test Bank",
            "account_last4": "1234", "opening_balance": "1000",
            "opening_balance_date": c.crm_today().isoformat(),
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            account = l.FinanceAccount.query.filter_by(cooperative_id=self.coop_a, name="Co-op Bank").one()
            account_id = account.id
        response = self.client.post("/finance/transactions", data={
            "transaction_type": "Income", "category": "Membership Fee", "amount": "300",
            "transaction_date": c.crm_today().isoformat(), "to_account_id": str(account_id),
            "source_type": "Contribution", "source_id": str(self.source_a),
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            tx = l.LedgerTransaction.query.filter_by(cooperative_id=self.coop_a, source_type="Contribution", source_id=self.source_a).one()
            tx_id = tx.id
        self.login_as("chair")
        response = self.client.post(f"/finance/transactions/{tx_id}/decision", data={"decision": "approve"})
        self.assertEqual(response.status_code, 302)
        return account_id, tx_id

    def test_ledger_separation_and_evidence_workflow(self):
        c, l, p = self.crm, self.ledger, self.p7
        self.login_as("treasurer")
        response = self.client.post("/finance/accounts", data={
            "name": "Co-op Bank", "account_type": "Bank Account", "institution": "Test Bank",
            "account_last4": "1234", "opening_balance": "1000",
            "opening_balance_date": c.crm_today().isoformat(),
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            account = l.FinanceAccount.query.filter_by(cooperative_id=self.coop_a, name="Co-op Bank").one()
            account_id = account.id

        response = self.client.post("/finance/transactions", data={
            "transaction_type": "Income", "category": "Membership Fee", "amount": "300",
            "transaction_date": c.crm_today().isoformat(), "to_account_id": str(account_id),
            "counterparty": "Farmer A", "reference": "LEDGER-PAY-001",
            "payment_method": "Cash", "project_reference": "Potato Seed Project",
            "notes": "Member payment for potato project",
            "source_type": "Contribution", "source_id": str(self.source_a),
        })
        self.assertEqual(response.status_code, 302)

        with c.app.app_context():
            tx = l.LedgerTransaction.query.filter_by(cooperative_id=self.coop_a, source_type="Contribution", source_id=self.source_a).one()
            tx_id = tx.id
            self.assertEqual(tx.status, "Pending Confirmation")
            self.assertEqual(tx.payment_method, "Cash")
            self.assertEqual(tx.project_reference, "Potato Seed Project")

        response = self.client.post(f"/finance/transactions/{tx_id}/decision", data={"decision": "approve"})
        self.assertEqual(response.status_code, 403)

        response = self.client.post("/finance/transactions", data={
            "transaction_type": "Income", "category": "Membership Fee", "amount": "300",
            "transaction_date": c.crm_today().isoformat(), "to_account_id": str(account_id),
            "source_type": "Contribution", "source_id": str(self.source_b),
        })
        self.assertEqual(response.status_code, 400)

        self.login_as("chair")
        response = self.client.post(f"/finance/transactions/{tx_id}/decision", data={"decision": "approve"})
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            tx = c.db.session.get(l.LedgerTransaction, tx_id)
            self.assertEqual(tx.status, "Confirmed")

        self.login_as("treasurer")
        response = self.client.post("/finance/transactions", data={
            "transaction_type": "Income", "category": "Membership Fee", "amount": "300",
            "transaction_date": c.crm_today().isoformat(), "to_account_id": str(account_id),
            "source_type": "Contribution", "source_id": str(self.source_a),
        })
        self.assertEqual(response.status_code, 409)

        with c.app.app_context():
            doc = p.CooperativeDocument(
                cooperative_id=self.coop_a,
                document_type="Receipt",
                title="Membership receipt",
                entity_type="LedgerTransaction",
                entity_id=tx_id,
                original_name="receipt.pdf",
                stored_name="ledger-test-receipt.pdf",
                file_sha256="0" * 64,
                uploaded_by_user_id=self.users["treasurer"],
            )
            c.db.session.add(doc)
            c.db.session.commit()

        response = self.client.get(f"/finance/transactions/{tx_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Membership receipt", response.data)
        self.assertIn(b"Potato Seed Project", response.data)
        self.assertIn(b"Cash", response.data)
        self.assertIn(b"Farmer A", response.data)
        self.assertIn(b"Attach Evidence", response.data)

        by_project = self.client.get("/finance/accounts?q=Potato+Seed+Project")
        self.assertEqual(by_project.status_code, 200)
        self.assertIn(b"LEDGER-PAY-001", by_project.data)
        by_method = self.client.get("/finance/accounts?payment_method=Cash")
        self.assertEqual(by_method.status_code, 200)
        self.assertIn(b"Potato Seed Project", by_method.data)
        no_match = self.client.get("/finance/accounts?q=definitely-no-such-ledger-record")
        self.assertEqual(no_match.status_code, 200)
        self.assertNotIn(f"View #{tx_id}".encode(), no_match.data)

    def test_loan_repayment_records_as_money_out_and_supports_evidence(self):
        c, l, p = self.crm, self.ledger, self.p7
        self.login_as("treasurer")
        response = self.client.post("/finance/accounts", data={
            "name": "Siyaphumla Main Bank",
            "account_type": "Bank Account",
            "institution": "Standard Bank",
            "account_last4": "7788",
            "opening_balance": "3000000",
            "opening_balance_date": c.crm_today().isoformat(),
        })
        self.assertEqual(response.status_code, 302)

        with c.app.app_context():
            account_id = l.FinanceAccount.query.filter_by(
                cooperative_id=self.coop_a,
                name="Siyaphumla Main Bank",
            ).one().id

        response = self.client.post("/finance/transactions", data={
            "transaction_type": "Expense",
            "category": "Loan Repayment",
            "amount": "50000",
            "transaction_date": c.crm_today().isoformat(),
            "from_account_id": str(account_id),
            "counterparty": "Standard Bank",
            "reference": "LOAN-SEP-2026",
            "payment_method": "EFT / Bank Transfer",
            "notes": "September loan instalment",
        })
        self.assertEqual(response.status_code, 302)

        with c.app.app_context():
            tx = l.LedgerTransaction.query.filter_by(
                cooperative_id=self.coop_a,
                reference="LOAN-SEP-2026",
            ).one()
            tx_id = tx.id
            self.assertEqual(tx.status, "Pending Confirmation")
            self.assertEqual(tx.transaction_type, "Expense")
            self.assertEqual(tx.category, "Loan Repayment")
            self.assertEqual(tx.counterparty, "Standard Bank")

            doc = p.CooperativeDocument(
                cooperative_id=self.coop_a,
                document_type="Receipt",
                title="Standard Bank repayment proof",
                entity_type="LedgerTransaction",
                entity_id=tx_id,
                original_name="loan-repayment-proof.pdf",
                stored_name="loan-repayment-proof-test.pdf",
                file_sha256="1" * 64,
                uploaded_by_user_id=self.users["treasurer"],
            )
            c.db.session.add(doc)
            c.db.session.commit()

        self.login_as("chair")
        response = self.client.post(
            f"/finance/transactions/{tx_id}/decision",
            data={"decision": "approve", "decision_note": "Proof checked."},
        )
        self.assertEqual(response.status_code, 302)

        with c.app.app_context():
            tx = c.db.session.get(l.LedgerTransaction, tx_id)
            account = c.db.session.get(l.FinanceAccount, account_id)
            self.assertEqual(tx.status, "Confirmed")
            self.assertAlmostEqual(account.confirmed_balance, 2950000.0)
            self.assertEqual(c.Membership.query.filter(
                c.Membership.farmer.has(fullname="Standard Bank")
            ).count(), 0)

        self.login_as("treasurer")
        response = self.client.get(f"/finance/transactions/{tx_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Loan Repayment", response.data)
        self.assertIn(b"Standard Bank", response.data)
        self.assertIn(b"Standard Bank repayment proof", response.data)

        response = self.client.get("/finance/accounts?group=Debt+Repayment")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"LOAN-SEP-2026", response.data)

    def test_same_page_ledger_cards_keep_user_at_results_section(self):
        self.login_as("treasurer")
        response = self.client.get("/finance/accounts")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('id="finance-categories"', page)
        self.assertIn('id="ledger-filters"', page)
        self.assertIn('id="account-balances"', page)
        self.assertIn('id="transaction-ledger"', page)
        self.assertIn('status=Confirmed#transaction-ledger', page)
        self.assertIn('status=Pending+Confirmation#transaction-ledger', page)

    def test_rejected_transaction_can_be_corrected_with_history_and_confirmed_is_locked(self):
        c, l = self.crm, self.ledger
        self.login_as("treasurer")
        response = self.client.post("/finance/accounts", data={
            "name": "Correction Bank", "account_type": "Bank Account", "opening_balance": "1000",
            "opening_balance_date": c.crm_today().isoformat(),
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            account_id = l.FinanceAccount.query.filter_by(cooperative_id=self.coop_a, name="Correction Bank").one().id

        response = self.client.post("/finance/transactions", data={
            "transaction_type": "Expense", "category": "Farm Inputs", "amount": "220",
            "transaction_date": c.crm_today().isoformat(), "from_account_id": str(account_id),
            "counterparty": "Input Supplier", "reference": "WRONG-REF",
            "payment_method": "Cash", "project_reference": "Potato Project",
            "notes": "Initial capture",
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            tx = l.LedgerTransaction.query.filter_by(cooperative_id=self.coop_a, reference="WRONG-REF").one()
            tx_id = tx.id

        self.login_as("chair")
        response = self.client.post(
            f"/finance/transactions/{tx_id}/decision",
            data={"decision": "reject", "decision_note": "Invoice total and reference do not match."},
        )
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            tx = c.db.session.get(l.LedgerTransaction, tx_id)
            self.assertEqual(tx.status, "Rejected")
            self.assertEqual(tx.decision_note, "Invoice total and reference do not match.")

        self.login_as("treasurer")
        response = self.client.post(f"/finance/transactions/{tx_id}/resubmit", data={
            "transaction_type": "Expense", "category": "Transport", "amount": "180",
            "transaction_date": c.crm_today().isoformat(), "from_account_id": str(account_id),
            "counterparty": "Input Supplier", "reference": "INV-180-CORRECT",
            "payment_method": "EFT / Bank Transfer", "project_reference": "Potato Project",
            "notes": "Corrected against supplier invoice",
            "correction_reason": "Corrected invoice amount, category and payment reference.",
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            tx = c.db.session.get(l.LedgerTransaction, tx_id)
            self.assertEqual(tx.status, "Pending Confirmation")
            self.assertAlmostEqual(tx.amount, 180.0)
            self.assertEqual(tx.category, "Transport")
            self.assertEqual(tx.reference, "INV-180-CORRECT")
            self.assertEqual(tx.payment_method, "EFT / Bank Transfer")
            self.assertIsNone(tx.decided_by_user_id)
            self.assertIsNone(tx.decided_at)
            self.assertIsNone(tx.decision_note)
            revision = l.LedgerTransactionRevision.query.filter_by(transaction_id=tx_id).one()
            self.assertEqual(revision.revision_number, 1)
            self.assertIn("Corrected invoice amount", revision.reason)
            self.assertEqual(revision.snapshot.get("status"), "Rejected")
            self.assertAlmostEqual(revision.snapshot.get("amount"), 220.0)
            self.assertEqual(revision.snapshot.get("category"), "Farm Inputs")
            self.assertEqual(revision.snapshot.get("reference"), "WRONG-REF")
            self.assertEqual(revision.snapshot.get("decision_note"), "Invoice total and reference do not match.")

        second_correction_while_pending = self.client.post(f"/finance/transactions/{tx_id}/resubmit", data={
            "transaction_type": "Expense", "category": "Transport", "amount": "170",
            "transaction_date": c.crm_today().isoformat(), "from_account_id": str(account_id),
            "correction_reason": "Should not be accepted while pending.",
        })
        # Invalid browser form state is normalized by the app shell to a safe feedback redirect.
        self.assertEqual(second_correction_while_pending.status_code, 303)

        detail = self.client.get(f"/finance/transactions/{tx_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Correction History", detail.data)
        self.assertIn(b"Corrected invoice amount", detail.data)
        self.assertIn(b"R 220.00", detail.data)

        self.login_as("chair")
        approved = self.client.post(
            f"/finance/transactions/{tx_id}/decision",
            data={"decision": "approve", "decision_note": "Corrected invoice verified."},
        )
        self.assertEqual(approved.status_code, 302)

        self.login_as("treasurer")
        locked = self.client.post(f"/finance/transactions/{tx_id}/resubmit", data={
            "transaction_type": "Expense", "category": "Transport", "amount": "160",
            "transaction_date": c.crm_today().isoformat(), "from_account_id": str(account_id),
            "correction_reason": "Attempt to overwrite confirmed entry.",
        })
        self.assertEqual(locked.status_code, 303)
        with c.app.app_context():
            tx = c.db.session.get(l.LedgerTransaction, tx_id)
            self.assertEqual(tx.status, "Confirmed")
            self.assertAlmostEqual(tx.amount, 180.0)
            self.assertEqual(l.LedgerTransactionRevision.query.filter_by(transaction_id=tx_id).count(), 1)

        confirmed_detail = self.client.get(f"/finance/transactions/{tx_id}")
        self.assertEqual(confirmed_detail.status_code, 200)
        self.assertIn(b"locked from direct editing", confirmed_detail.data)

    def test_account_reconciliation_uses_confirmed_ledger_and_is_scoped(self):
        c, l, p = self.crm, self.ledger, self.p7
        account_id, _ = self._create_confirmed_income()

        self.login_as("treasurer")
        response = self.client.post("/finance/reconciliations", data={
            "finance_account_id": str(account_id),
            "statement_date": c.crm_today().isoformat(),
            "statement_balance": "1290",
            "notes": "R10 bank timing difference",
        })
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            row = l.FinanceReconciliation.query.filter_by(cooperative_id=self.coop_a, finance_account_id=account_id).one()
            reconciliation_id = row.id
            self.assertAlmostEqual(row.book_balance, 1300.0)
            self.assertAlmostEqual(row.difference, -10.0)
            self.assertEqual(row.status, "Pending Review")

        response = self.client.post("/finance/reconciliations", data={
            "finance_account_id": str(account_id),
            "statement_date": c.crm_today().isoformat(),
            "statement_balance": "1290",
        })
        self.assertEqual(response.status_code, 409)

        self.login_as("other_chair")
        self.assertEqual(self.client.get(f"/finance/reconciliations/{reconciliation_id}").status_code, 404)

        self.login_as("chair")
        response = self.client.post(f"/finance/reconciliations/{reconciliation_id}/review")
        self.assertEqual(response.status_code, 302)
        with c.app.app_context():
            row = c.db.session.get(l.FinanceReconciliation, reconciliation_id)
            self.assertEqual(row.status, "Reviewed")
            self.assertEqual(row.reviewed_by_user_id, self.users["chair"])

        with c.app.app_context():
            doc = p.CooperativeDocument(
                cooperative_id=self.coop_a,
                document_type="Financial Document",
                title="Bank statement evidence",
                entity_type="FinanceReconciliation",
                entity_id=reconciliation_id,
                original_name="statement.pdf",
                stored_name="ledger-test-statement.pdf",
                file_sha256="1" * 64,
                uploaded_by_user_id=self.users["treasurer"],
            )
            c.db.session.add(doc)
            c.db.session.commit()

        self.login_as("treasurer")
        response = self.client.get(f"/finance/reconciliations/{reconciliation_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Bank statement evidence", response.data)
        self.assertIn(b"R 1,300.00", response.data)

    def test_reconciliation_self_review_is_blocked(self):
        c, l = self.crm, self.ledger
        account_id, _ = self._create_confirmed_income()
        with c.app.app_context():
            row = l.FinanceReconciliation(
                cooperative_id=self.coop_a,
                finance_account_id=account_id,
                statement_date=c.crm_today(),
                statement_balance=1300,
                book_balance=1300,
                difference=0,
                status="Pending Review",
                prepared_by_user_id=self.users["chair"],
            )
            c.db.session.add(row)
            c.db.session.commit()
            reconciliation_id = row.id
        self.login_as("chair")
        response = self.client.post(f"/finance/reconciliations/{reconciliation_id}/review")
        self.assertEqual(response.status_code, 403)

    def test_opening_balance_effective_date_controls_historical_reconciliation(self):
        c, l = self.crm, self.ledger
        today = c.crm_today()
        yesterday = today - timedelta(days=1)
        self.login_as("treasurer")

        missing_date = self.client.post("/finance/accounts", data={
            "name": "Undated Opening", "account_type": "Bank Account", "opening_balance": "500",
        })
        self.assertEqual(missing_date.status_code, 303)
        with c.app.app_context():
            self.assertIsNone(l.FinanceAccount.query.filter_by(cooperative_id=self.coop_a, name="Undated Opening").first())

        created = self.client.post("/finance/accounts", data={
            "name": "Dated Opening", "account_type": "Bank Account", "opening_balance": "500",
            "opening_balance_date": today.isoformat(),
        })
        self.assertEqual(created.status_code, 302)
        with c.app.app_context():
            account = l.FinanceAccount.query.filter_by(cooperative_id=self.coop_a, name="Dated Opening").one()
            account_id = account.id
            self.assertEqual(account.opening_balance_date, today)
            self.assertAlmostEqual(account.confirmed_balance, 500.0)

        before = self.client.post("/finance/reconciliations", data={
            "finance_account_id": str(account_id),
            "statement_date": yesterday.isoformat(),
            "statement_balance": "0",
        })
        self.assertEqual(before.status_code, 302)

        on_date = self.client.post("/finance/reconciliations", data={
            "finance_account_id": str(account_id),
            "statement_date": today.isoformat(),
            "statement_balance": "500",
        })
        self.assertEqual(on_date.status_code, 302)

        with c.app.app_context():
            before_row = l.FinanceReconciliation.query.filter_by(finance_account_id=account_id, statement_date=yesterday).one()
            on_date_row = l.FinanceReconciliation.query.filter_by(finance_account_id=account_id, statement_date=today).one()
            self.assertAlmostEqual(before_row.book_balance, 0.0)
            self.assertAlmostEqual(before_row.difference, 0.0)
            self.assertAlmostEqual(on_date_row.book_balance, 500.0)
            self.assertAlmostEqual(on_date_row.difference, 0.0)


if __name__ == "__main__":
    unittest.main()
