import os
from dataclasses import dataclass

from dotenv import load_dotenv
from fastapi import Depends, Header, HTTPException, status
from supabase import Client, create_client


load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    raise ValueError(
        "SUPABASE_URL and SUPABASE_SECRET_KEY must be configured."
    )


supabase_admin: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY,
)


@dataclass(frozen=True)
class TenantContext:
    user_id: str
    business_id: str
    business_name: str
    role: str


def extract_bearer_token(
    authorization: str | None,
) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
        )

    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header.",
        )

    return token.strip()


async def get_tenant_context(
    authorization: str | None = Header(
        default=None,
        alias="Authorization",
    ),
) -> TenantContext:
    token = extract_bearer_token(authorization)

    try:
        user_response = supabase_admin.auth.get_user(token)
        user = user_response.user

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="The authentication session is invalid.",
            )

        membership_response = (
            supabase_admin.table("business_users")
            .select(
                "business_id, role, is_active, "
                "businesses(id, name, status)"
            )
            .eq("user_id", str(user.id))
            .eq("is_active", True)
            .limit(1)
            .execute()
        )

        memberships = membership_response.data or []

        if not memberships:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No active GoodKeeper workspace was found.",
            )

        membership = memberships[0]
        business = membership.get("businesses") or {}

        if business.get("status") != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This GoodKeeper workspace is not active.",
            )

        return TenantContext(
            user_id=str(user.id),
            business_id=str(membership["business_id"]),
            business_name=str(
                business.get("name")
                or "GoodKeeper Workspace"
            ),
            role=str(
                membership.get("role")
                or "viewer"
            ),
        )

    except HTTPException:
        raise

    except Exception as error:
        print(
            f"[Tenant Context] Authentication failed: {error}"
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate the authentication session.",
        ) from error


def require_owner_or_admin(
    tenant: TenantContext = Depends(
        get_tenant_context
    ),
) -> TenantContext:
    if tenant.role not in {
        "owner",
        "admin",
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner or administrator access is required.",
        )

    return tenant