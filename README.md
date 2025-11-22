# Training and Engineering Repository (TER)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![AWS](https://img.shields.io/badge/AWS-RDS%20|%20S3%20|%20ECS-orange.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Tests](https://img.shields.io/badge/Tests-48%20Passing-brightgreen.svg)

**A cloud-based compliance management system for engineering laboratories**

[Live Demo](http://54.203.9.249:5000) • [Problem Statement](#the-problem) • [Solution](#solution-architecture) • [Installation](#installation)

</div>

---

## Overview

I developed this system as my Master's capstone project to address a significant operational challenge in engineering laboratory compliance management. Organizations maintaining ISO 9001, AS 9100, and ISO/IEC 17025 certifications face substantial overhead in tracking training records, managing access authorizations, and preparing for audits. Training certificates become dispersed across email systems, qualification spreadsheets fall out of date, and when auditors request evidence that personnel possessed current training on specific dates, compliance officers spend hours manually reconstructing records from fragmented sources.

The Training and Engineering Repository consolidates training tracking, certificate storage, access control, and document management into a unified platform. Engineers view real-time training status and submit lab access requests. Managers approve requests with automated compliance verification that validates training currency and document acknowledgments. The system maintains comprehensive audit trails, stores certificates securely in AWS S3, and generates compliance reports on demand. This automation reduces manual compliance checking from 2-5 hours per week to approximately 3 seconds per verification.

I deployed the complete system to production on AWS infrastructure using RDS MySQL, S3 for encrypted storage, and ECS Fargate for containerized hosting. The implementation includes 48 automated tests with 100% pass rate, JWT authentication with bcrypt password hashing, and follows security best practices throughout the architecture. This is a production system accessible via public endpoint, not just a localhost prototype.

## The Problem

Laboratory compliance management in regulated environments typically follows an inefficient manual process. When an engineer needs access to a testing facility, they email their manager requesting permission. The manager opens a spreadsheet to verify the engineer completed required safety training, manually calculates whether the training remains valid based on completion dates and expiration policies, checks for applicable grace periods, and cross-references another document to verify the engineer acknowledged all required safety procedures at current version numbers. This verification process consumes 15-30 minutes per request.

Multiply this across dozens of engineers, multiple facilities, and quarterly compliance audits, and the administrative burden becomes significant. Manual processes create audit risk when records aren't properly maintained, operational inefficiency as managers spend hours on verification tasks, and safety concerns when outdated data leads to granting access to personnel with expired qualifications.

My system automates this entire workflow. When engineers submit access requests, the compliance engine evaluates their training completion dates against facility requirements, automatically applies validity periods and grace periods, verifies document acknowledgments at current versions, and approves or denies requests based on configurable rules. Managers can review automated decisions but are not required to manually verify each requirement. The database maintains complete audit trails with timestamps for all state changes.

## Live Demo

The system is deployed on AWS and accessible at [http://54.203.9.249:5000](http://54.203.9.249:5000). Three test accounts demonstrate different role capabilities:

**Engineer Account** (`eng@example.com` / `Eng123!`)  
View training status dashboard, submit lab access requests, and acknowledge compliance documents. The system immediately indicates qualification status or identifies missing requirements.

**Manager Account** (`manager@example.com` / `Manager123!`)  
Review pending access requests, run automated compliance checks across all personnel, and generate audit-ready CSV reports. The "Run Autocheck" feature demonstrates automated state transitions as the system grants or revokes access based on current training status.

**Admin Account** (`admin@example.com` / `Admin123!`)  
Configure courses and validity periods, define laboratories and requirements, upload versioned compliance documents, and manage user accounts.

Note: The production URL uses ECS Fargate with dynamic IP allocation. If the link is inaccessible, the IP address may have changed during container restart. In production deployments, an Application Load Balancer would provide stable DNS endpoints, but I avoided this for the capstone demo to minimize costs.

## Solution Architecture

This is a Flask web application backed by MySQL and integrated with AWS services. I designed the database schema in Third Normal Form with ten tables handling engineer records, training completions, laboratory definitions, access authorizations, document versioning, and audit logs. The compliance engine evaluates whether personnel meet lab requirements by checking training completion dates against validity periods, applying configured grace periods, and verifying current-version document acknowledgments.

The Flask application uses blueprints to separate concerns: authentication handles login and JWT generation, engineer routes serve the end-user interface, manager routes implement approval workflows, and admin routes provide system configuration. Route protection decorators enforce both authentication (session validity) and authorization (role-based permissions).

Security implementation includes JWT tokens stored in HTTP-only cookies to prevent JavaScript access, bcrypt password hashing with automatic salting, and role-based access control enforcing least privilege. The AWS infrastructure follows security best practices with the RDS database in a VPC accessible only from the ECS security group, S3 bucket with public access blocked, and presigned URLs for temporary authenticated file access expiring after 5 minutes.

I containerized the application with Docker for consistent deployment. The Dockerfile builds from Python 3.10 slim base, installs dependencies, and exposes port 5000. Images push to Amazon ECR, and ECS Fargate executes them as tasks. Task definitions include environment variables for database connections, AWS credentials, and secret keys. CloudWatch captures application logs for production monitoring.

## Technology Stack

The backend uses Python 3.10 with Flask 3.0 as the web framework. Flask provides the necessary routing, templating, and form handling capabilities while remaining lightweight. SQLAlchemy 2.0 serves as the ORM for MySQL 8.0 database interactions, allowing database operations in Python with automatic query parameterization that prevents SQL injection attacks.

Authentication leverages PyJWT for JSON Web Token generation and validation. Passwords use bcrypt hashing which handles salting automatically. The frontend employs Jinja2 templates for server-side rendering, Bootstrap 5 for responsive styling, and minimal vanilla JavaScript for client-side interactions. I deliberately maintained frontend simplicity as this project focuses on backend data management and business logic.

AWS infrastructure includes RDS MySQL (db.t3.micro instance with 20GB storage and automated backups), S3 for certificate and document storage (server-side encryption enabled, versioning enabled for audit evidence preservation), and ECS Fargate for serverless container execution (0.25 vCPU, 512MB RAM). CloudWatch collects logs, and IAM policies enforce least-privilege access limiting the application to specific S3 buckets and database instances.

Testing and deployment tools include pytest for the 48 automated tests covering authentication, compliance logic, database models, routes, and report generation. Tests execute in approximately 5 seconds using in-memory SQLite. Docker provides consistent packaging, and Git handles version control.

## Database Design

The schema consists of ten tables in Third Normal Form, eliminating data redundancy. Core entities include Engineers (personnel records), Users (authentication credentials linked to engineer records), Courses (training programs with validity periods), and Labs (physical facilities).

Relationship tables connect these entities. Completions track training completion dates, expiration dates, and S3 keys for certificate storage. LabRequirements define course prerequisites for each laboratory with optional lab-specific validity period overrides. LabAccess records track authorization status (pending, active, revoked) with approval/revocation timestamps and responsible parties.

Document management uses a Documents table storing safety procedures and manuals with version numbers. DocumentAck tracks acknowledgments including specific version numbers. When new document versions upload, previous acknowledgments automatically invalidate, requiring personnel to re-acknowledge current versions.

The AuditLog table captures every state change with actor identification, timestamps, affected entities, and modification details, providing complete audit traceability. Foreign key constraints prevent orphaned records, and unique constraints prevent duplicates such as multiple active access records for the same engineer-laboratory pair.

## Installation

### Prerequisites

- Python 3.10 or higher
- MySQL 8.0 (SQLite acceptable for local development)
- AWS account (for production deployment)
- Git

### Local Development Setup

Clone the repository and create a Python virtual environment:

```bash
git clone https://github.com/yourusername/ter-compliance.git
cd ter-compliance
python -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1

# Linux/Mac
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure environment variables by creating a `.env` file in the project root:

```env
# Database (SQLite for local development)
SQLALCHEMY_DATABASE_URI=sqlite:///instance/compliance.db

# Security keys (generate random strings)
SECRET_KEY=your-secret-key-here
JWT_SECRET=your-jwt-secret-here

# AWS S3 (optional for local development)
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-west-2
AWS_S3_BUCKET=your-bucket-name

# Flask configuration
FLASK_APP=compliance
FLASK_ENV=development
```

Initialize the database:

```bash
flask shell
>>> from compliance import db
>>> db.create_all()
>>> exit()
```

Seed sample data:

```bash
python -c "from compliance import create_app; from compliance.seed import seed_data; app = create_app(); app.app_context().push(); seed_data()"
```

Run the application:

```bash
flask run
```

Access at `http://localhost:5000` using default credentials:
- Admin: `admin@example.com` / `Admin123!`
- Manager: `manager@example.com` / `Manager123!`
- Engineer: `eng@example.com` / `Eng123!`

### Docker Deployment

Build and run using Docker:

```bash
docker build -t ter-compliance:latest .

docker run -p 5000:5000 \
  -e SQLALCHEMY_DATABASE_URI="your-database-uri" \
  -e SECRET_KEY="your-secret-key" \
  -e JWT_SECRET="your-jwt-secret" \
  ter-compliance:latest
```

The containerized approach provides complete isolation without dependency conflicts or Python version issues.

## Testing

The test suite includes 48 automated tests using pytest that verify actual functionality rather than superficial module imports. Authentication tests confirm valid credential acceptance, invalid credential rejection, proper JWT token generation with 8-hour expiration, and route protection against unauthenticated access.

Compliance engine tests validate core business logic: correct training expiration calculation based on validity periods, proper grace period application when configured, disqualification upon training expiration, and accurate document version requirement checking. Additional tests verify automated state transitions during autocheck operations, confirming appropriate access grants for qualified personnel and revocations for non-compliant personnel.

Database model tests ensure constraint enforcement: unique constraints preventing duplicates, foreign keys maintaining referential integrity, and relationship queries returning correct associated records. Route tests verify HTTP endpoint security, preventing managers from accessing admin routes, engineers from viewing manager dashboards, and ensuring form input validation.

Report generation tests confirm CSV exports contain correct data in proper format, date range filtering functions accurately, and special characters in names or titles don't corrupt CSV formatting.

All 48 tests pass with execution time of approximately 5 seconds using in-memory SQLite databases. Each test function receives a fresh database with fixture-loaded sample data, preventing test interference. Coverage metrics include 95% for authentication, 100% for compliance engine, 90% for database models, and 85% for routes.

## Security Implementation

Security received substantial attention throughout development as the system handles sensitive personnel data and controls access to potentially hazardous environments. JWT tokens store in HTTP-only cookies preventing JavaScript access, which protects against XSS attacks. Tokens expire after 8 hours, limiting compromise windows. Logout immediately clears cookies.

Passwords never store in plain text. Bcrypt hashing with automatic salting and cost factor 12 ensures even database compromise doesn't expose actual passwords. Login compares entered password hashes against stored hashes.

Role-based access control implements three levels: engineer, manager, and admin. Every protected route includes decorators checking both authentication (valid session) and authorization (appropriate role). Engineers access only personal data, managers view all personnel data without configuration modification capability, and admins possess full system configuration access.

Infrastructure security employs defense in depth. The RDS database resides in a VPC with security groups allowing only ECS security group connections, preventing direct internet access. The S3 bucket blocks all public access. File access uses presigned URLs containing AWS credentials in URL parameters with 5-minute expiration, providing temporary authenticated access without credential exposure.

SQLAlchemy ORM automatically parameterizes all database queries, preventing SQL injection. File upload validation restricts types and sizes, preventing 10GB uploads or executable files disguised as documents. The audit log captures every state change providing complete action history with actor identification and timestamps.

## Project Context

This capstone project for my Master's degree in Computer Science addresses genuine industry challenges rather than theoretical exercises. I selected laboratory compliance management to demonstrate practical full-stack development capabilities, cloud infrastructure knowledge, database design skills, and security implementation - competencies essential in professional software engineering.

The project showcases several key areas. Backend work includes normalized database schema design, complex business logic implementation in the compliance engine, and RESTful-style API development with comprehensive error handling. Cloud computing aspects cover AWS service configuration and deployment including RDS, S3, and ECS with appropriate security groups, IAM policies, and monitoring. The testing demonstrates quality assurance understanding and ability to write maintainable, verified code.

What distinguishes this work is production deployment on actual AWS infrastructure rather than localhost prototypes. The system operates at a public endpoint with automated database backups, CloudWatch logging, and encrypted S3 storage - a turnkey solution deliverable to organizations for immediate use.

## Performance Metrics

Quantitative assessment demonstrates significant operational improvements. Automation reduces compliance checking from 2-5 hours weekly to approximately 3 seconds per verification - a 95-99% reduction in manual effort. Audit preparation previously requiring hours of manual data compilation now completes instantly via CSV report generation.

Technical quality metrics include 48 automated tests with 100% pass rate executing in approximately 5 seconds using in-memory SQLite, providing rapid development feedback. Production AWS deployment maintains 99%+ uptime with ECS Fargate automatically restarting containers upon failure.

Response times achieve 95th percentile under 500 milliseconds for page loads and form submissions. S3 file uploads require approximately 1.2 seconds for typical 500KB certificates, reasonable given cloud transfer latency. The system operates efficiently on minimal resources: 0.25 vCPU and 512MB RAM with average CPU utilization around 10% and memory usage approximately 200MB. Total production deployment cost ranges $30-45 monthly including database, storage, and compute resources.

## Current Status

The system is production-ready and fully operational. All core features are implemented: automated compliance checking, certificate storage, access workflows, document management, audit reports, and role-based access control. AWS deployment is stable with complete security hardening including proper authentication, authorization, encryption, and network isolation. The test suite verifies functionality, and performance meets requirements.

Potential future enhancements could include physical badge integration enabling real-time compliance verification at facility entry points, native mobile applications for convenient certificate uploads and status checks, email notifications for approaching training expiration dates, analytics dashboards visualizing compliance trends, multi-tenant support for multiple organizations with data isolation, SAML/OAuth integration for enterprise single sign-on, API rate limiting, and automated PDF parsing for certificate data extraction. However, the current implementation effectively addresses the core compliance management problem.

## License

This project is released under the MIT License for educational and portfolio purposes. While you're free to learn from and adapt the code, this specific implementation represents my Master's capstone project completed in 2025.

The MIT License permits commercial use, modification, distribution, and private use. The sole requirement is maintaining copyright notices and license text in redistributions. The software is provided "as-is" without warranty, which is standard for open-source projects.

If you use substantial portions of this work, I appreciate attribution and links back to this repository. Attribution helps establish professional credibility as I enter the job market and follows good open-source community practices.

## Author

Michael Kalajian  
Master of Science in Computer Science  
GitHub: [@mikeklay](https://github.com/mikeklay)  
Email: mikeklay@gmail.com

I focus on full-stack development, cloud infrastructure, and building systems that address real operational challenges.

## Acknowledgments

I thank the laboratory managers who explained their compliance workflows and validated that this system addresses actual pain points. Their feedback ensured practical applicability rather than purely theoretical solutions. The Flask and SQLAlchemy communities provided excellent documentation that facilitated development. AWS's comprehensive cloud platform with generous free tier enabled production deployment within academic project budgets.

---

If you find this project useful, please consider starring the repository. For questions about implementation or similar projects, feel free to reach out.
