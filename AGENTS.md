StudySmart — Agent Development Instructions
Project Overview
StudySmart is an individual Advanced Web Mapping / Location-Based Services university assignment. It helps students find study spaces in Dublin using an interactive map, spatial searches and facility filters.

The project is assessed for spatial database design, Django architecture, REST API design, frontend usability, Docker deployment, security, code quality and documentation. Prioritise simple, reliable, explainable engineering rather than extra features.
Core Features (MVP)
1. Interactive Leaflet map of study locations: libraries and study-friendly cafés only. University campuses are search starting points, not study-space records.
2. Radius search around a user-selected point.
3. Nearest study-space search with distance information.
4. Filters for space type and confirmed facilities (indoor seating, Wi-Fi, power outlets) when reliable attributes exist. A quiet-environment filter is out of scope: no reliable source data exists.
5. Authenticated administrator CRUD for study spaces.
6. Administrative-area containment and counts for a distinct third spatial query.
Do not add live occupancy, reservations, ratings, route optimisation, user accounts or recommendation AI unless expressly requested and approved.
Approved Technology Stack
- Python; Django / GeoDjango; Django REST Framework
- PostgreSQL with PostGIS
- Leaflet.js with OpenStreetMap base tiles
- HTML, CSS, JavaScript and Bootstrap 5
- Docker Compose with separate Django, PostGIS and pgAdmin4 services; optional Nginx
- Git / GitHub
Prefer standard library and established framework functionality. Explain and request approval for new dependencies.
Spatial Data and Database
- StudySpace: name, type, location as PointField (SRID 4326), optional address, description, facility attributes and source metadata.
- AdministrativeArea: name and boundary (PolygonField or MultiPolygonField as appropriate).
- Use migrations, appropriate spatial indexes and reproducible import commands.
- Implement spatial operations in GeoDjango/PostGIS, not ad hoc JavaScript math: within-radius, nearest and containment/aggregation.
- Validate latitude (-90..90), longitude (-180..180), distance/radius bounds and required fields.
- Handle coordinate reference system transformations explicitly and test imported geometry.
- Never invent real-world facility attributes. Treat unknown as unknown, not false. Distinguish authoritative, OpenStreetMap, manually verified and demo data; record source and retrieval date.
- Make imports idempotent and document dataset licences and attribution.
Architecture and Style
- Keep responsibilities separated into models, serializers, views, URL routes, optional service functions, templates and static assets.
- Use readable, minimal implementations. Avoid premature abstractions, unnecessary packages and sprawling front-end frameworks.
- Use clear naming and concise comments for non-obvious spatial logic.
- Provide consistent JSON API responses and appropriate HTTP status codes.
- Public endpoints can allow read access; writes require authenticated administrator permissions.
- Handle failures and empty results clearly in both API and UI.
- Preserve mobile responsiveness and accessible labels/controls.
Agent Workflow
For each GitHub Issue:
1. Read this file, the README and the relevant Issue; inspect existing implementation.
2. Propose a short plan with files, data assumptions, tests and risks. Do not modify files until approved.
3. Work only on the approved issue and feature branch.
4. Keep the change small and reviewable, with relevant automated tests.
5. Run available checks/tests and accurately report outcomes; never claim tests passed if not run.
6. Summarise changes, commands, design decisions and anything unresolved.
7. Explain new code clearly enough for the student to present and defend it.
8. Suggest a concise commit message and pull-request description.
Do not commit, push, merge, delete unrelated files, access secrets or run destructive commands without explicit approval.
Security and Deployment
- Use environment variables and maintain .env.example; do not commit .env or credentials.
- Configure Docker networking and persistent PostGIS volumes.
- Apply appropriate Django security settings, permissions, CSRF protection and allowed-host rules.
- Avoid exposing database and admin services unnecessarily.
- Test local startup, migration, import and application use from a clean setup.
Testing and Documentation
- Test models, serializers, CRUD permission rules, valid/invalid input and the three spatial operations.
- Include edge cases: missing coordinates, invalid radii, no matches, missing facility attributes and duplicate imports.
- Maintain README setup instructions, endpoint documentation, architecture diagram, schema documentation, screenshots, known limitations and source attribution.
- Document meaningful engineering decisions and test results.
Academic Integrity
- The student owns architecture decisions, code review, verification and presentation.
- Attribute external code and datasets as required; document AI assistance according to module policy.
- Never present generated code or unverified data as independently verified work.
Definition of Done
An issue is complete only when its acceptance criteria are met, relevant tests pass or limitations are disclosed, security and data handling are considered, documentation is updated, and the student understands the result.