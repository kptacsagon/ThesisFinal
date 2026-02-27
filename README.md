# Thesis Management System

A Flask-based web application for managing thesis submissions, reviews, and approvals.

## Features

- **Role-based access**: student, advisor, admin
- **JWT authentication** (24-hour tokens)
- **Thesis workflow**: submit → review → approved / needs_revision / rejected
- Single-page frontend with no external CSS frameworks

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000` in your browser.

## API Endpoints

| Method | Endpoint | Description | Roles |
|--------|----------|-------------|-------|
| POST | `/api/auth/register` | Register new user | public |
| POST | `/api/auth/login` | Login, receive JWT | public |
| GET | `/api/theses` | List theses | all |
| POST | `/api/theses` | Submit thesis | student |
| GET | `/api/theses/<id>` | Get thesis detail | all |
| PUT | `/api/theses/<id>` | Update thesis | student (owner, pending/needs_revision) |
| POST | `/api/theses/<id>/review` | Submit review | advisor, admin |
| GET | `/api/users` | List all users | admin |

## Running Tests

```bash
python -m pytest tests/ -v
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `dev-secret-key-change-in-production` | JWT signing key |
| `DATABASE_URL` | `sqlite:///thesis.db` | SQLAlchemy database URL |