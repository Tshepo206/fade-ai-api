from db_manager import supabase


class ServiceManager:
    """Tenant-scoped service access."""

    @staticmethod
    def get_services(business_id: str) -> list:
        if not business_id:
            return []
        try:
            response = (
                supabase.table("services").select("*")
                .eq("business_id", business_id).order("service_name").execute()
            )
            return response.data or []
        except Exception as error:
            print(f"Tenant service lookup failed: {error}")
            return []

    @staticmethod
    def get_service_by_id(business_id: str, service_id: int):
        if not business_id:
            return None
        try:
            response = (
                supabase.table("services").select("*")
                .eq("business_id", business_id).eq("id", service_id)
                .limit(1).execute()
            )
            return response.data[0] if response.data else None
        except Exception as error:
            print(f"Tenant service lookup by ID failed: {error}")
            return None
