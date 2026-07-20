from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from availability_manager import AvailabilityManager
from booking_manager import BookingManager
from customer_manager import CustomerManager
from dashboard_analytics_manager import DashboardAnalyticsManager
from reconciliation_manager import ReconciliationManager
from report_manager import ReportManager
from service_manager import ServiceManager
from tenant_context import TenantContext, get_tenant_context
from transaction_history import get_transaction_history


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


class BlockSlotRequest(BaseModel):
    start_datetime: str
    end_datetime: str
    reason: str = "Dashboard manual block"


class CustomerCreateRequest(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=120)
    phone_number: str = Field(..., min_length=8, max_length=30)
    email: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=2000)


class ManualBookingRequest(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=120)
    phone_number: str = Field(..., min_length=8, max_length=30)
    service_id: int = Field(..., ge=1)
    appointment_timestamp: str
    customer_email: Optional[str] = Field(default=None, max_length=255)
    customer_notes: Optional[str] = Field(default=None, max_length=2000)


@router.get("/workspace")
def get_current_workspace(tenant: TenantContext = Depends(get_tenant_context)):
    return {"success": True, "workspace": {"business_id": tenant.business_id,
            "business_name": tenant.business_name, "role": tenant.role, "user_id": tenant.user_id}}


@router.get("/summary")
def get_dashboard_summary(period: str = Query(default="today", pattern="^(today|week|month)$"),
                          tenant: TenantContext = Depends(get_tenant_context)):
    return DashboardAnalyticsManager.get_dashboard_summary(tenant.business_id, period)


@router.get("/bookings")
def get_dashboard_bookings(limit: int = Query(default=20, ge=1, le=100),
                           tenant: TenantContext = Depends(get_tenant_context)):
    bookings = BookingManager.get_upcoming_bookings(tenant.business_id, limit)
    return {"success": True, "count": len(bookings), "bookings": bookings}


@router.get("/today-bookings")
def get_today_bookings(tenant: TenantContext = Depends(get_tenant_context)):
    bookings = BookingManager.get_today_bookings(tenant.business_id)
    return {"success": True, "count": len(bookings), "bookings": bookings}


@router.post("/manual-booking")
def create_manual_booking(payload: ManualBookingRequest,
                          tenant: TenantContext = Depends(get_tenant_context)):
    result = BookingManager.create_manual_booking(tenant.business_id, payload.phone_number,
        payload.customer_name, payload.service_id, payload.appointment_timestamp,
        payload.customer_email, payload.customer_notes)
    if not result.get("success"):
        message = result.get("error") or "The manual booking could not be created."
        lower = message.lower()
        status_code = 409 if any(value in lower for value in ("already booked", "blocked", "not available")) else 400 if any(value in lower for value in ("past", "invalid", "required", "does not exist", "must begin")) else 500
        raise HTTPException(status_code=status_code, detail=message)
    return {"success": True, "message": "Booking created successfully.", "booking": result.get("booking"),
            "customer": result.get("customer"), "service": result.get("service")}


@router.get("/customers")
def get_customers(search: Optional[str] = Query(default=None, max_length=120),
                  limit: int = Query(default=50, ge=1, le=500),
                  tenant: TenantContext = Depends(get_tenant_context)):
    customers = CustomerManager.get_all_customers(tenant.business_id, search, limit)
    return {"success": True, "count": len(customers), "customers": customers}


@router.post("/customers")
def create_or_update_customer(payload: CustomerCreateRequest,
                              tenant: TenantContext = Depends(get_tenant_context)):
    result = CustomerManager.create_or_update_customer(tenant.business_id, payload.phone_number,
        payload.customer_name, payload.email, payload.notes)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "The customer could not be saved.")
    return {"success": True, "message": "Customer saved successfully.", "customer": result.get("customer")}


@router.get("/top-customers")
def get_top_customers(period: str = Query(default="month", pattern="^(today|week|month|all)$"),
                      limit: int = Query(default=10, ge=1, le=50),
                      tenant: TenantContext = Depends(get_tenant_context)):
    customers = DashboardAnalyticsManager.get_top_customers(tenant.business_id, period, limit)
    return {"success": True, "period": period, "count": len(customers), "customers": customers}


@router.get("/services")
def get_dashboard_services(tenant: TenantContext = Depends(get_tenant_context)):
    services = [service for service in ServiceManager.get_services(tenant.business_id) if service.get("is_active", True)]
    return {"success": True, "count": len(services), "services": services}


@router.get("/transactions")
def get_dashboard_transactions(period: str = Query(default="last_30_days", pattern="^(last_7_days|last_30_days|this_month|last_month|quarter|year|last_year|custom)$"),
                               start_date: Optional[str] = Query(default=None), end_date: Optional[str] = Query(default=None),
                               limit: int = Query(default=500, ge=1, le=2000),
                               tenant: TenantContext = Depends(get_tenant_context)):
    result = get_transaction_history(tenant.business_id, period, start_date, end_date, limit)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Transaction history could not be retrieved.")
    return {"success": True, "period": result.get("period"), "start_date": result.get("start_date"),
            "end_date": result.get("end_date"), "start_datetime": result.get("start_datetime"),
            "end_datetime": result.get("end_datetime"), "count": len(result.get("transactions") or []),
            "summary": result.get("summary"), "transactions": result.get("transactions") or [], "error": None}


@router.get("/calendar")
def get_dashboard_calendar(view: str = Query(default="day", pattern="^(day|week|month)$"),
                           target_date: Optional[str] = Query(default=None),
                           tenant: TenantContext = Depends(get_tenant_context)):
    try:
        start_date = datetime.fromisoformat(target_date) if target_date else datetime.now()
    except ValueError as error:
        raise HTTPException(status_code=400, detail="The target date is invalid.") from error
    if view == "day":
        start_dt = start_date.replace(hour=0, minute=0, second=0, microsecond=0); end_dt = start_dt + timedelta(days=1)
    elif view == "week":
        start_dt = (start_date - timedelta(days=start_date.weekday())).replace(hour=0, minute=0, second=0, microsecond=0); end_dt = start_dt + timedelta(days=7)
    else:
        start_dt = start_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt.replace(year=start_dt.year + 1, month=1) if start_dt.month == 12 else start_dt.replace(month=start_dt.month + 1)
    slots = BookingManager.get_calendar_slots(tenant.business_id, start_dt.isoformat(), end_dt.isoformat())
    return {"success": True, "view": view, "start_datetime": start_dt.isoformat(), "end_datetime": end_dt.isoformat(), "count": len(slots), "slots": slots}


@router.post("/calendar/block")
def block_calendar_time(payload: BlockSlotRequest, tenant: TenantContext = Depends(get_tenant_context)):
    if not AvailabilityManager.block_time_range(tenant.business_id, payload.start_datetime, payload.end_datetime, payload.reason or "Blocked time"):
        raise HTTPException(status_code=400, detail="Could not block the selected time.")
    return {"success": True, "message": "Time blocked successfully."}


@router.delete("/calendar/unblock/{slot_id}")
def unblock_calendar_slot(slot_id: int, tenant: TenantContext = Depends(get_tenant_context)):
    if not AvailabilityManager.unblock_slot(tenant.business_id, slot_id):
        raise HTTPException(status_code=400, detail="Could not unblock the selected slot.")
    return {"success": True, "message": "Slot unblocked successfully."}


@router.get("/revenue-trends")
def get_revenue_trends(period: str = Query(default="week", pattern="^(week|month)$"),
                       tenant: TenantContext = Depends(get_tenant_context)):
    return {"success": True, "period": period, "trends": DashboardAnalyticsManager.get_revenue_trends(tenant.business_id, period)}


@router.get("/revenue-by-service")
def get_revenue_by_service(period: str = Query(default="month", pattern="^(today|week|month)$"),
                           tenant: TenantContext = Depends(get_tenant_context)):
    return {"success": True, "period": period, "services": DashboardAnalyticsManager.get_revenue_by_service(tenant.business_id, period)}


@router.get("/ai-recommendations")
def get_ai_recommendations(period: str = Query(default="today", pattern="^(today|week|month)$"),
                           tenant: TenantContext = Depends(get_tenant_context)):
    return {"success": True, "period": period, "recommendations": DashboardAnalyticsManager.get_ai_recommendations(tenant.business_id, period)}


@router.get("/bank-reconciliation")
def get_bank_reconciliation(period: str = Query(default="today", pattern="^(today|week|month)$"),
                            tenant: TenantContext = Depends(get_tenant_context)):
    return {"success": True, "period": period, "reconciliation": DashboardAnalyticsManager.get_bank_reconciliation(tenant.business_id, period)}


@router.post("/bank-reconciliation/upload")
async def upload_bank_statement(period: str = Query(default="month", pattern="^(today|week|month)$"), file: UploadFile = File(...),
                                tenant: TenantContext = Depends(get_tenant_context)):
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="The uploaded bank statement is empty.")
        return ReconciliationManager.reconcile_statement(tenant.business_id, file.filename or "statement", file_bytes, period)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Bank reconciliation failed: {str(error)}") from error


@router.get("/monthly-report")
def get_monthly_report(tenant: TenantContext = Depends(get_tenant_context)):
    return {"success": True, "report": ReportManager.get_monthly_report(tenant.business_id)}


@router.get("/monthly-report/pdf")
def download_monthly_report_pdf(tenant: TenantContext = Depends(get_tenant_context)):
    try:
        file_path = ReportManager.generate_monthly_pdf(tenant.business_id, tenant.business_name)
        return FileResponse(path=file_path, media_type="application/pdf", filename=file_path.split("/")[-1])
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Monthly PDF report generation failed: {str(error)}") from error
