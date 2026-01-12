# Step 1: Authentication & Project Foundation - Quick Start

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Update the `.env` file with a secure SECRET_KEY (min 32 characters)

## Running the Application

```bash
uvicorn app.main:app --reload
```

The API will be available at: http://localhost:8000

Interactive API docs: http://localhost:8000/docs

## Testing the API

### 1. Register a User
```bash
curl -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret123"}'
```

### 2. Login to Get Token
```bash
curl -X POST "http://localhost:8000/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=alice&password=secret123"
```

### 3. Create a Project (use token from step 2)
```bash
curl -X POST "http://localhost:8000/projects/" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -d '{"name": "My Project"}'
```

### 4. Add Member to Project (owner only)
```bash
# First register another user
curl -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"username": "bob", "password": "secret456"}'

# Then add as member (use Alice's token)
curl -X POST "http://localhost:8000/projects/1/members" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -d '{"username": "bob"}'
```

### 5. Test Authorization (should fail with 403)
```bash
# Login as bob
curl -X POST "http://localhost:8000/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=bob&password=secret456"

# Try to add member with Bob's token (should fail)
curl -X POST "http://localhost:8000/projects/1/members" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer BOBS_TOKEN_HERE" \
  -d '{"username": "charlie"}'
```

## File Structure

```
.
├── app/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── auth.py         # JWT logic, password hashing, dependencies
│   │   └── config.py       # Security settings (Secret keys)
│   ├── __init__.py
│   ├── models.py           # User and Project DB models
│   ├── schemas.py          # Pydantic models for API requests/responses
│   └── main.py             # App entry point and Auth/Project routes
├── .env                    # Environment secrets
└── requirements.txt        # Python dependencies
```

## Key Features Implemented

✅ JWT-based authentication with python-jose
✅ Password hashing with bcrypt
✅ User registration and login
✅ Project creation (owner assigned automatically)
✅ Member management with owner-only authorization
✅ Many-to-many relationship between Users and Projects
✅ OAuth2 compatible token endpoint
