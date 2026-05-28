# Graph Report - medical-receptionist  (2026-05-28)

## Corpus Check
- 13 files · ~8,418 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 160 nodes · 279 edges · 14 communities (13 shown, 1 thin omitted)
- Extraction: 82% EXTRACTED · 18% INFERRED · 0% AMBIGUOUS · INFERRED: 49 edges (avg confidence: 0.52)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7abff32a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]

## God Nodes (most connected - your core abstractions)
1. `GoogleCalendarService` - 22 edges
2. `Scheduler` - 21 edges
3. `Agent` - 19 edges
4. `StateManager` - 18 edges
5. `str` - 16 edges
6. `webhook_receiver()` - 16 edges
7. `Session` - 12 edges
8. `Setup Instructions` - 10 edges
9. `normalize_phone()` - 8 edges
10. `int` - 8 edges

## Surprising Connections (you probably didn't know these)
- `Depends` --uses--> `Agent`  [INFERRED]
  main.py → agent.py
- `bool` --uses--> `Agent`  [INFERRED]
  main.py → agent.py
- `datetime` --uses--> `Agent`  [INFERRED]
  main.py → agent.py
- `int` --uses--> `Agent`  [INFERRED]
  main.py → agent.py
- `str` --uses--> `Agent`  [INFERRED]
  main.py → agent.py

## Communities (14 total, 1 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.11
Nodes (31): datetime, str, booking_summary(), create_appointment_from_booking_data(), ensure_sqlite_schema_upgrades(), extract_booking_details(), get_slots(), is_booking_message() (+23 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (26): 1. Clone the repository, 2. Create a Python Virtual Environment, 3. Activate the Virtual Environment, 4. Install Dependencies, 5. Google Calendar API Credentials (OAuth2), 6. Set up Environment Variables, 7. Run the FastAPI Server, 8. Access the Chat UI (+18 more)

### Community 2 - "Community 2"
Cohesion: 0.15
Nodes (13): Depends, get_all_appointments(), get_all_patients(), login_for_access_token(), Authenticates a user and returns an access token., reset_user_state(), StateResetRequest, Scheduler (+5 more)

### Community 3 - "Community 3"
Cohesion: 0.13
Nodes (14): address, clinic_name, doctors, faqs, hours, friday, monday, saturday (+6 more)

### Community 4 - "Community 4"
Cohesion: 0.21
Nodes (11): str, BaseModel, create_access_token(), get_current_user(), Creates an access token for authentication., Verifies the authenticity of a JWT token., Fetches the current authenticated user based on the provided token., Token (+3 more)

### Community 5 - "Community 5"
Cohesion: 0.24
Nodes (6): bool, datetime, int, str, date, GoogleCalendarService

### Community 6 - "Community 6"
Cohesion: 0.31
Nodes (3): ConversationState, StateManager, str

### Community 8 - "Community 8"
Cohesion: 0.43
Nodes (5): Base, Appointment, Conversation, Patient, User

### Community 9 - "Community 9"
Cohesion: 0.33
Nodes (6): bool, int, cancel_appointment_record(), extract_appointment_id(), Extract appointment ID from structured data or free text., Cancel appointment in local DB by ID.

## Knowledge Gaps
- **29 isolated node(s):** `bool`, `clinic_name`, `address`, `phone`, `monday` (+24 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `GoogleCalendarService` connect `Community 5` to `Community 0`, `Community 2`, `Community 4`, `Community 8`, `Community 9`?**
  _High betweenness centrality (0.110) - this node is a cross-community bridge._
- **Why does `Scheduler` connect `Community 2` to `Community 0`, `Community 4`, `Community 5`, `Community 8`, `Community 9`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Why does `StateManager` connect `Community 6` to `Community 0`, `Community 9`, `Community 2`, `Community 4`?**
  _High betweenness centrality (0.076) - this node is a cross-community bridge._
- **Are the 12 inferred relationships involving `GoogleCalendarService` (e.g. with `Depends` and `bool`) actually correct?**
  _`GoogleCalendarService` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `Scheduler` (e.g. with `Depends` and `bool`) actually correct?**
  _`Scheduler` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `Agent` (e.g. with `Depends` and `bool`) actually correct?**
  _`Agent` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `StateManager` (e.g. with `Depends` and `bool`) actually correct?**
  _`StateManager` has 11 INFERRED edges - model-reasoned connections that need verification._