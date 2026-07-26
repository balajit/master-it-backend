# Master It Backend API

A FastAPI-based REST service for managing courses with local and Google OAuth authentication.

## Quick Start

```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env   # add your GOOGLE_CLIENT_ID and JWT_SECRET

# Start server
./start.sh             # http://localhost:5000
```

## Authentication

All protected endpoints require a Bearer token in the `Authorization` header.

### Register (local account)

```bash
curl -X POST http://localhost:5000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secret","name":"Jane"}'
```

Response:
```json
{"access_token": "<jwt>", "token_type": "bearer"}
```

### Login (local account)

```bash
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secret"}'
```

### Google Sign-In

```bash
curl -X POST http://localhost:5000/api/auth/google \
  -H "Content-Type: application/json" \
  -d '{"id_token":"<google-id-token>"}'
```

All auth endpoints return the same `access_token` response. Store it and send with every request:

```
Authorization: Bearer <access_token>
```

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Health check |
| GET | `/api/spec` | Configurable | OpenAPI 3.1 JSON spec |
| POST | `/api/auth/register` | No | Create local account |
| POST | `/api/auth/login` | No | Sign in with email/password |
| POST | `/api/auth/google` | No | Sign in with Google |
| GET | `/api/me` | Yes | Current user profile |
| GET | `/api/courses` | Yes | List all courses |
| POST | `/api/courses` | Yes | Create a course |

## Course Object

```json
{
  "id": 1,
  "title": "Intro to CS",
  "description": "Fundamentals",
  "number_of_credits": 3,
  "difficulty": "beginner",
  "status": "OPEN",
  "owner_id": 1
}
```

### Status Values

| Value | Meaning |
|-------|---------|
| `COMING_SOON` | Not yet available (default) |
| `OPEN` | Currently available |
| `CLOSED` | No longer available |

## OpenAPI Spec

Fetch the full spec at runtime to generate clients:

```bash
# Public (default)
curl http://localhost:5000/api/spec

# Protected (set OPENAPI_PROTECTED=true in .env)
curl http://localhost:5000/api/spec -H "Authorization: Bearer <token>"
```

## Integration Example (JavaScript)

```javascript
const API = "http://localhost:5000";

async function register(email, password, name) {
  const res = await fetch(`${API}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, name }),
  });
  const { access_token } = await res.json();
  return access_token;
}

async function getCourses(token) {
  const res = await fetch(`${API}/api/courses`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.json();
}

async function createCourse(token, course) {
  const res = await fetch(`${API}/api/courses`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(course),
  });
  return res.json();
}

// Usage
const token = await register("me@example.com", "pass", "Me");
const courses = await getCourses(token);
await createCourse(token, {
  title: "Math 101",
  description: "Algebra basics",
  number_of_credits: 3,
  difficulty: "beginner",
  status: "COMING_SOON",
});
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_CLIENT_ID` | Yes | — | Google OAuth client ID |
| `JWT_SECRET` | No | `dev-secret-...` | Secret for signing JWTs |
| `OPENAPI_PROTECTED` | No | `false` | Require auth for `/api/spec` |
