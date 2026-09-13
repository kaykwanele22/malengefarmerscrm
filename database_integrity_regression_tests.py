import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DatabaseIntegrityRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="malenge_db_integrity_")
        cls.db_path = Path(cls.tempdir.name) / "integrity.db"
        cls.repo_root = Path(__file__).resolve().parent

        env = os.environ.copy()
        env.update({
            "DATABASE_URL": f"sqlite:///{cls.db_path.as_posix()}",
            "SECRET_KEY": "database-integrity-regression-secret",
            "APP_ENV": "testing",
            "TWO_FACTOR_REQUIRED": "false",
        })
        result = subprocess.run(
            [sys.executable, "-m", "flask", "--app", "app", "db", "upgrade"],
            cwd=cls.repo_root,
            env=env,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Fresh database migration failed for integrity tests.\n"
                + result.stdout
                + "\n"
                + result.stderr
            )

        cls.conn = sqlite3.connect(cls.db_path)
        cls.conn.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tempdir.cleanup()

    def setUp(self):
        self.conn.execute("BEGIN")
        self._seed_cooperatives()

    def tearDown(self):
        self.conn.rollback()

    def _seed_cooperatives(self):
        self.conn.executemany(
            """
            INSERT INTO cooperative
                (id, name, cooperative_type, parent_id, registration_number, code, location, status, created_at)
            VALUES (?, ?, 'Primary', NULL, NULL, ?, 'Malenge', 'Active', CURRENT_TIMESTAMP)
            """,
            [
                (1001, "Integrity Primary A", "INT-A"),
                (1002, "Integrity Primary B", "INT-B"),
            ],
        )

    def _insert_farmer(self, farmer_id, cooperative_id, fullname="Integrity Farmer", phone="0711111111"):
        self.conn.execute(
            """
            INSERT INTO farmer
                (id, cooperative_id, fullname, phone, email, location, farm_size, primary_crop, status, created_at)
            VALUES (?, ?, ?, ?, NULL, 'Malenge', NULL, NULL, 'Active', CURRENT_TIMESTAMP)
            """,
            (farmer_id, cooperative_id, fullname, phone),
        )

    def _insert_farm(self, farm_id, cooperative_id, farmer_id, name="Integrity Farm", location="Malenge Plot 1", size=2.5):
        self.conn.execute(
            """
            INSERT INTO farm
                (id, cooperative_id, name, farmer_id, location, size, farming_type, main_crop, registration_date, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Crop', NULL, CURRENT_TIMESTAMP, 'Active')
            """,
            (farm_id, cooperative_id, name, farmer_id, location, size),
        )

    def test_exact_duplicate_farmer_is_blocked_without_overblocking_shared_phone(self):
        self._insert_farmer(2001, 1001)

        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_farmer(2002, 1001)

        # A family/shared contact number remains allowed when the farmer identity differs.
        self._insert_farmer(2003, 1001, fullname="Different Farmer", phone="0711111111")

    def test_farm_must_belong_to_same_cooperative_as_farmer(self):
        self._insert_farmer(2001, 1001)

        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_farm(3001, 1002, 2001)

        self._insert_farm(3002, 1001, 2001)

    def test_exact_duplicate_farm_and_negative_size_are_blocked(self):
        self._insert_farmer(2001, 1001)
        self._insert_farm(3001, 1001, 2001)

        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_farm(3002, 1001, 2001)

        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_farm(
                3003,
                1001,
                2001,
                name="Second Farm",
                location="Malenge Plot 2",
                size=-1,
            )

    def test_crop_cannot_point_to_farm_owned_by_another_cooperative(self):
        self._insert_farmer(2001, 1001)
        self._insert_farm(3001, 1001, 2001)

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO crop
                    (id, cooperative_id, name, farm_id, variety, planting_date,
                     expected_harvest_date, area_planted, status, notes, created_at)
                VALUES (4001, 1002, 'Potato', 3001, NULL, NULL, NULL, 1.0, 'Planted', NULL, CURRENT_TIMESTAMP)
                """
            )

        self.conn.execute(
            """
            INSERT INTO crop
                (id, cooperative_id, name, farm_id, variety, planting_date,
                 expected_harvest_date, area_planted, status, notes, created_at)
            VALUES (4002, 1001, 'Potato', 3001, NULL, NULL, NULL, 1.0, 'Planted', NULL, CURRENT_TIMESTAMP)
            """
        )

    def test_membership_and_contribution_amount_constraints_are_enforced(self):
        self._insert_farmer(2001, 1001)

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO membership
                    (id, cooperative_id, farmer_id, member_number, membership_type,
                     join_date, fee_amount, fee_paid, status, notes, created_at, updated_at)
                VALUES (5001, 1001, 2001, 'INT-0001', 'Primary', NULL, -1, 0,
                        'Active', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )

        self.conn.execute(
            """
            INSERT INTO membership
                (id, cooperative_id, farmer_id, member_number, membership_type,
                 join_date, fee_amount, fee_paid, status, notes, created_at, updated_at)
            VALUES (5002, 1001, 2001, 'INT-0002', 'Primary', NULL, 300, 0,
                    'Active', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO contribution
                    (id, cooperative_id, farmer_id, membership_id, amount, contribution_date,
                     category, method, reference, status, notes, created_at)
                VALUES (6001, 1001, 2001, 5002, 0, '2026-09-13', 'Membership Fee',
                        'Cash', NULL, 'Pending Confirmation', NULL, CURRENT_TIMESTAMP)
                """
            )

    def test_composite_foreign_keys_exist_in_migrated_schema(self):
        farm_fks = self.conn.execute("PRAGMA foreign_key_list('farm')").fetchall()
        crop_fks = self.conn.execute("PRAGMA foreign_key_list('crop')").fetchall()
        membership_fks = self.conn.execute("PRAGMA foreign_key_list('membership')").fetchall()

        self.assertTrue(any(row[2] == "farmer" and row[3] == "cooperative_id" for row in farm_fks))
        self.assertTrue(any(row[2] == "farm" and row[3] == "cooperative_id" for row in crop_fks))
        self.assertTrue(any(row[2] == "farmer" and row[3] == "cooperative_id" for row in membership_fks))


if __name__ == "__main__":
    unittest.main()
