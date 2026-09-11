# 🌱 Malenge Farmers CRM

**Agricultural cooperative management, governance and accountability software built with Python and Flask.**

Malenge Farmers CRM is a practical management system designed to help agricultural cooperatives organise farmers, farms, membership, leadership, governance records and accountable execution of cooperative decisions.

Rather than functioning only as a contact database, the project is evolving into an **accountability and evidence system**: decisions can be linked to official meeting evidence, assigned to responsible executives, tracked against deadlines, supported by proof, and independently verified before closure.

## Why this project exists

Agricultural cooperatives need more than spreadsheets and informal records. Membership, farm information, leadership responsibilities, resolutions, deadlines and supporting documents can easily become disconnected.

Malenge Farmers CRM brings these records into one structured system so cooperative leadership can answer questions such as:

- Who are our registered farmers and members?
- Which farms are associated with them?
- Who currently holds an executive role?
- What was officially decided at a meeting?
- Who is responsible for implementing the decision?
- What is the deadline and current progress?
- What evidence proves that the work was completed?
- Who independently verified completion?

## ✨ Core capabilities

### 👨🏾‍🌾 Farmer and farm management
- Maintain farmer records.
- Maintain farm records and farmer relationships.
- Search and manage agricultural information.
- Track active records through the CRM interface.

### 🤝 Cooperative membership
- Cooperative membership records and status.
- Membership fee tracking and validation.
- Support for cooperative organisational structures.

### 👥 Executive governance
- Executive leadership records.
- Role-based access and permissions.
- Cooperative-specific governance visibility.
- Administrative tools for assigning system access.

### 📋 Accountability and resolutions
The Phase 6 accountability workflow is designed around traceable evidence:

`Meeting evidence → Chairperson confirmation → Resolution → Certification → Accountability task → Progress → Evidence → Independent verification → Closed`

The system supports:

- meeting evidence registration;
- resolution records linked to confirmed meetings;
- responsible executive assignment;
- priorities and deadlines;
- progress tracking;
- evidence uploads;
- independent verification;
- permanent progress history;
- accountability status monitoring.

### 🔐 Security
- Password hashing through Werkzeug.
- Role and permission controls.
- Two-factor authentication functionality.
- Environment-based configuration.
- Evidence stored outside the public static directory.
- Evidence file validation and SHA-256 fingerprinting in the accountability workflow.

### 📱 Responsive interface
The application includes responsive templates and static assets intended for desktop, tablet and mobile use.

## 🛠 Technology stack

- **Python** — application language
- **Flask** — web framework
- **Flask-SQLAlchemy** — ORM/database layer
- **Flask-Migrate** — database migrations
- **PostgreSQL / psycopg** — production database support
- **SQLite** — local development support
- **Werkzeug** — security and Flask utilities
- **Gunicorn** — production WSGI server
- **python-dotenv** — environment configuration
- **cryptography** — security functionality
- **qrcode** — QR-code support for authentication workflows
- **HTML / CSS / JavaScript** — frontend interface

## 🧪 Testing and validation

The repository includes regression and validation suites covering areas such as:

- full application regression;
- cooperative membership;
- executive functionality;
- permissions;
- security;
- mobile behaviour;
- Phase 6 accountability workflows.

This project is being developed in phases so new functionality can be validated against existing behaviour.

## 🚀 Local development

### 1. Clone the repository

```bash
git clone <repository-url>
cd malengefarmerscrm
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

On macOS/Linux:

```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the provided example configuration:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Then configure the local values required by the application. **Never commit the real `.env` file.**

### 5. Prepare the database

The project uses Flask-Migrate for schema migrations. Review `DATABASE_MIGRATION.md` and the migration files before upgrading an existing database.

### 6. Run the application

```bash
python app.py
```

## 📂 Project structure

```text
malengefarmerscrm/
├── app.py                         # Main Flask application
├── templates/                     # Jinja/HTML interface
├── static/                        # CSS, JavaScript and public assets
├── migrations/                    # Database migrations
├── docs/                          # Supporting project documentation
├── requirements.txt               # Python dependencies
├── .env.example                   # Safe configuration example
├── PHASE4_EXECUTIVES.md           # Executive-management phase notes
├── PHASE5_MEMBERSHIP.md           # Membership phase documentation
├── PHASE6_ACCOUNTABILITY.md       # Accountability architecture
└── *_regression_tests.py          # Regression/validation suites
```

## 🗺 Development roadmap

Current and planned development includes:

- richer accountability reporting and exports;
- formal amendments to confirmed meeting evidence;
- executive delegation and acting-authority workflows;
- executive handover checklists;
- expanded Treasurer evidence and approval records;
- evidence-aware backup and restore;
- cross-primary MFPSU accountability oversight;
- further dashboard and analytics improvements;
- production deployment hardening.

## 📸 Screenshots

Project screenshots will be added as the portfolio presentation layer is completed.

Suggested showcase screens include:

1. Dashboard
2. Farmers register
3. Farms register
4. Cooperative membership
5. Executive management
6. Accountability register
7. Meeting evidence
8. Resolution/task verification

## 🌍 Project context

Malenge Farmers CRM is being built around real agricultural cooperative administration needs. The goal is to demonstrate how practical software can improve record keeping, governance, transparency and operational accountability in community-based agricultural organisations.

## 👨🏾‍💻 Developer

Developed by **Nate / kaykwanele22** as an ongoing Python, Flask and full-stack software engineering project.

This repository is also part of a broader developer portfolio focused on practical systems for agriculture, business, finance and automation.

## ⚠️ Project status

**Active development.** Interfaces, database structures and workflows may continue to evolve as additional phases are implemented and tested.

---

If you are reviewing this project as part of my developer portfolio, start with `PHASE6_ACCOUNTABILITY.md` for an example of the governance and evidence architecture currently being developed.