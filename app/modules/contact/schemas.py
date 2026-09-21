from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ContactInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr = Field(max_length=254)
    message: str = Field(min_length=1, max_length=5000)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()
