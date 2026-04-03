from sqlalchemy.orm import Session

from app.core.security import PasswordTooLongError, create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.category_service import CategoryService
from app.services.goal_service import GoalService


class UserAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InactiveUserError(Exception):
    pass


class InvalidPasswordError(Exception):
    pass


class AuthService:
    def __init__(self, db: Session):
        self.user_repo = UserRepository(db)

    def register(self, *, email: str, password: str, full_name: str | None = None) -> User:
        if self.user_repo.get_by_email(email):
            raise UserAlreadyExistsError("User with this email already exists")
        try:
            password_hash = hash_password(password)
        except PasswordTooLongError as exc:
            raise InvalidPasswordError('Password is too long. Maximum allowed length is 72 bytes in UTF-8.') from exc
        user = self.user_repo.create(email=email, password_hash=password_hash, full_name=full_name)
        CategoryService(self.user_repo.db).ensure_default_categories(user_id=user.id)
        GoalService(self.user_repo.db).ensure_system_goals(user.id)
        return user

    def login(self, *, email: str, password: str) -> str:
        user = self.user_repo.get_by_email(email)
        if not user:
            raise InvalidCredentialsError("Invalid email or password")
        try:
            password_ok = verify_password(password, user.password_hash)
        except PasswordTooLongError:
            raise InvalidCredentialsError("Invalid email or password")
        if not password_ok:
            raise InvalidCredentialsError("Invalid email or password")
        if not user.is_active:
            raise InactiveUserError("User is inactive")
        return create_access_token(subject=user.id)