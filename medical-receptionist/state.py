import datetime
import json
import logging

from sqlalchemy import Column, String, DateTime
from sqlalchemy.exc import IntegrityError

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
    """Persist conversation state using a short-lived DB session per operation.

    A SQLAlchemy Session is not safe to share across concurrent requests. The
    former process-wide session could be used by multiple chat requests at once.
    """

    @staticmethod
    def _get_or_create(db, user_id: str):
        state = (
            db.query(ConversationState)
            .filter(ConversationState.user_id == user_id)
            .first()
        )
        if state is not None:
            return state

        state = ConversationState(
            user_id=user_id,
            state="GREETING",
            data=json.dumps({"unknown_count": 0}),
        )
        db.add(state)
        try:
            db.commit()
            db.refresh(state)
            return state
        except IntegrityError:
            # Another request may have created this user's row concurrently.
            db.rollback()
            state = (
                db.query(ConversationState)
                .filter(ConversationState.user_id == user_id)
                .first()
            )
            if state is None:
                raise
            return state

    def get_state(self, user_id: str):
        db = SessionLocal()
        try:
            state = self._get_or_create(db, user_id)
            db.refresh(state)
            db.expunge(state)
            return state
        finally:
            db.close()

    def set_state(self, user_id: str, new_state: str, data: dict = None):
        db = SessionLocal()
        try:
            state = self._get_or_create(db, user_id)
            state.state = new_state
            state.last_updated = datetime.datetime.now()
            if data is not None:
                try:
                    existing_data = json.loads(state.data or "{}")
                except (TypeError, ValueError):
                    existing_data = {}
                if not isinstance(existing_data, dict):
                    existing_data = {}
                state.data = json.dumps({**existing_data, **data})
            db.commit()
            db.refresh(state)
            db.expunge(state)
            return state
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def reset_state(self, user_id: str):
        db = SessionLocal()
        try:
            state = self._get_or_create(db, user_id)
            state.state = "GREETING"
            state.last_updated = datetime.datetime.now()
            state.data = "{}"
            db.commit()
            db.refresh(state)
            db.expunge(state)
            return state
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def close(self):
        # Kept for backwards compatibility. Sessions are now closed per method.
        return None


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
