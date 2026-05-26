import datetime
import json
import logging

from sqlalchemy import Column, String, DateTime

from database import Base, SessionLocal

logger = logging.getLogger(__name__)


class ConversationState(Base):
    __tablename__ = "conversation_states"

    user_id = Column(String, primary_key=True, index=True)
    state = Column(String, default="GREETING")
    last_updated = Column(DateTime, default=datetime.datetime.now)
    data = Column(String, default="{}")  # JSON string

    def __repr__(self):
        return f"<ConversationState(user_id='{self.user_id}', state='{self.state}')>"


class StateManager:
    def __init__(self):
        self.db = SessionLocal()

    def get_state(self, user_id: str):
        state = (
            self.db.query(ConversationState)
            .filter(ConversationState.user_id == user_id)
            .first()
        )
        if not state:
            state = ConversationState(user_id=user_id, state="GREETING", data=json.dumps({"unknown_count": 0}))
            self.db.add(state)
            self.db.commit()
            self.db.refresh(state)
        return state

    def set_state(self, user_id: str, new_state: str, data: dict = None):
        state = self.get_state(user_id)
        state.state = new_state
        state.last_updated = datetime.datetime.now()
        if data is not None:
            # Merge new data with existing data if present
            existing_data = json.loads(state.data or "{}")
            merged_data = {**existing_data, **data}
            state.data = json.dumps(merged_data)
        self.db.commit()
        self.db.refresh(state)
        return state

    def reset_state(self, user_id: str):
        state = self.get_state(user_id)
        state.state = "GREETING"
        state.last_updated = datetime.datetime.now()
        state.data = "{}"
        self.db.commit()
        self.db.refresh(state)
        return state

    def close(self):
        self.db.close()


if __name__ == "__main__":
    state_manager = StateManager()

    user1_id = "user123"
    user2_id = "user456"

    state1 = state_manager.get_state(user1_id)
    print(f"User {user1_id} initial state: {state1.state}")

    state_manager.set_state(user1_id, "BOOKING", {"reason": "dental checkup"})
    state1 = state_manager.get_state(user1_id)
    print(f"User {user1_id} new state: {state1.state}, Data: {state1.data}")

    state2 = state_manager.get_state(user2_id)
    print(f"User {user2_id} initial state: {state2.state}")

    state_manager.set_state(
        user1_id,
        "CONFIRM",
        {"reason": "dental checkup", "date": "2024-12-25", "time": "10:00 AM"},
    )
    state1 = state_manager.get_state(user1_id)
    print(f"User {user1_id} updated state: {state1.state}, Data: {state1.data}")

    state_manager.reset_state(user1_id)
    state1 = state_manager.get_state(user1_id)
    print(f"User {user1_id} reset state: {state1.state}, Data: {state1.data}")

    state_manager.close()
