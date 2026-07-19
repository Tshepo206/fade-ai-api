from datetime import datetime, timedelta
from typing import Optional

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from bank_reconciliation import SmartBankReconciliationManager
from db_manager import BarberDatabaseManager
from monthly_report_generator import MonthlyReportGenerator


router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
)


# ------------------------------------------------------------------
# REQUEST MODELS
# ------------------------------------------------------------------

class BlockSlotRequest(BaseModel):
    start_datetime: str
    end_datetime: str
    reason: str = "Dashboard manual block"


class CustomerCreateRequest(BaseModel):
    customer_name: str = Field(
        ...,
        min_length=1,
        max_length=120,
    )
    phone_number: str = Field(
        ...,
        min_length=8,
        max_length=30,
    )
    email: Optional[str] = Field(
        default=None,
        max_length=255,
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=2000,
    )


class ManualBookingRequest(BaseModel):
    customer_name: str = Field(
        ...,
        min_length=1,
        max_length=120,
    )
    phone_number: str = Field(
        ...,
        min_length=8,
        max_length=30,
    )
    service_id: int = Field(
        ...,
        ge=1,
    )
    appointment_timestamp: str
    customer_email: Optional[str] = Field(
        default=None,
        max_length=255,
    )
    customer_notes: Optional[str] = Field(
        default=None,
        max_length=2000,
    )


# ------------------------------------------------------------------
# DASHBOARD SUMMARY
# ------------------------------------------------------------------

@router.get("/summary")
def get_dashboard_summary(
    period: str = Query(
        default="today",
        pattern="^(today|week|month)$",
    )
):
    return BarberDatabaseManager.get_dashboard_summary(period)


# ------------------------------------------------------------------
# BOOKINGS
# ------------------------------------------------------------------

@router.get("/bookings")
def get_dashboard_bookings(
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    )
):
    bookings = BarberDatabaseManager.get_upcoming_bookings(
        limit=limit
    )

    return {
        "success": True,
        "count": len(bookings),
        "bookings": bookings,
    }


@router.get("/today-bookings")
def get_today_bookings():
    bookings = BarberDatabaseManager.get_today_bookings()

    return {
        "success": True,
        "count": len(bookings),
        "bookings": bookings,
    }


@router.post("/manual-booking")
def create_manual_booking(
    payload: ManualBookingRequest,
):
    result = BarberDatabaseManager.create_manual_booking(
        phone_number=payload.phone_number,
        customer_name=payload.customer_name,
        service_id=payload.service_id,
        appointment_timestamp=payload.appointment_timestamp,
        customer_email=payload.customer_email,
        customer_notes=payload.customer_notes,
    )

    if not result.get("success"):
        error_message = (
            result.get("error")
            or "The manual booking could not be created."
        )

        lower_error = error_message.lower()

        if (
            "already booked" in lower_error
            or "blocked" in lower_error
            or "not available" in lower_error
        ):
            status_code = 409
        elif (
            "past" in lower_error
            or "invalid" in lower_error
            or "required" in lower_error
            or "does not exist" in lower_error
            or "must begin" in lower_error
        ):
            status_code = 400
        else:
            status_code = 500

        raise HTTPException(
            status_code=status_code,
            detail=error_message,
        )

    return {
        "success": True,
        "message": "Booking created successfully.",
        "booking": result.get("booking"),
        "customer": result.get("customer"),
        "service": result.get("service"),
    }


# ------------------------------------------------------------------
# CUSTOMERS
# ------------------------------------------------------------------

@router.get("/customers")
def get_customers(
    search: Optional[str] = Query(
        default=None,
        max_length=120,
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
    ),
):
    customers = BarberDatabaseManager.get_all_clients(
        search_term=search,
        limit=limit,
    )

    return {
        "success": True,
        "count": len(customers),
        "customers": customers,
    }


@router.post("/customers")
def create_or_update_customer(
    payload: CustomerCreateRequest,
):
    result = BarberDatabaseManager.create_or_update_client(
        phone_number=payload.phone_number,
        first_name=payload.customer_name,
        email=payload.email,
        notes=payload.notes,
    )

    if not result.get("success"):
        error_message = (
            result.get("error")
            or "The customer could not be saved."
        )

        raise HTTPException(
            status_code=400,
            detail=error_message,
        )

    return {
        "success": True,
        "message": "Customer saved successfully.",
        "customer": result.get("customer"),
    }


@router.get("/top-customers")
def get_top_customers(
    period: str = Query(
        default="month",
        pattern="^(today|week|month|all)$",
    ),
    limit: int = Query(
        default=10,
        ge=1,
        le=50,
    ),
):
    customers = BarberDatabaseManager.get_top_customers(
        period=period,
        limit=limit,
    )

    return {
        "success": True,
        "period": period,
        "count": len(customers),
        "customers": customers,
    }


# ------------------------------------------------------------------
# SERVICES
# ------------------------------------------------------------------

@router.get("/services")
def get_dashboard_services():
    services = BarberDatabaseManager.fetch_services()

    active_services = [
        service
        for service in services
        if service.get("is_active", True)
    ]

    return {
        "success": True,
        "count": len(active_services),
        "services": active_services,
    }


# ------------------------------------------------------------------
# TRANSACTIONS
# ------------------------------------------------------------------

@router.get("/transactions")
def get_dashboard_transactions(
    limit: int = Query(
        default=20,
        ge=1,
        le=500,
    )
):
    transactions = BarberDatabaseManager.get_recent_transactions(
        limit=limit
    )

    return {
        "success": True,
        "count": len(transactions),
        "transactions": transactions,
    }


# ------------------------------------------------------------------
# CALENDAR
# ------------------------------------------------------------------

@router.get("/calendar")
def get_dashboard_calendar(
    view: str = Query(
        default="day",
        pattern="^(day|week|month)$",
    ),
    target_date: Optional[str] = Query(default=None),
):
    try:
        if target_date:
            start_date = datetime.fromisoformat(target_date)
        else:
            start_date = datetime.now()

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail="The target date is invalid.",
        ) from error

    if view == "day":
        start_dt = start_date.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        end_dt = start_dt + timedelta(days=1)

    elif view == "week":
        start_dt = start_date - timedelta(
            days=start_date.weekday()
        )
        start_dt = start_dt.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        end_dt = start_dt + timedelta(days=7)

    else:
        start_dt = start_date.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        if start_dt.month == 12:
            end_dt = start_dt.replace(
                year=start_dt.year + 1,
                month=1,
            )
        else:
            end_dt = start_dt.replace(
                month=start_dt.month + 1
            )

    slots = BarberDatabaseManager.get_calendar_slots(
        start_datetime=start_dt.isoformat(),
        end_datetime=end_dt.isoformat(),
    )

    return {
        "success": True,
        "view": view,
        "start_datetime": start_dt.isoformat(),
        "end_datetime": end_dt.isoformat(),
        "count": len(slots),
        "slots": slots,
    }


@router.post("/calendar/block")
def block_calendar_time(
    payload: BlockSlotRequest,
):
    success = BarberDatabaseManager.block_time_range(
        start_datetime=payload.start_datetime,
        end_datetime=payload.end_datetime,
        reason=payload.reason or "Blocked time",
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Could not block the selected time.",
        )

    return {
        "success": True,
        "message": "Time blocked successfully.",
    }


@router.delete("/calendar/unblock/{slot_id}")
def unblock_calendar_slot(
    slot_id: int,
):
    success = BarberDatabaseManager.unblock_slot(slot_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Could not unblock the selected slot.",
        )

    return {
        "success": True,
        "message": "Slot unblocked successfully.",
    }


# ------------------------------------------------------------------
# REVENUE ANALYTICS
# ------------------------------------------------------------------

@router.get("/revenue-trends")
def get_revenue_trends(
    period: str = Query(
        default="week",
        pattern="^(week|month)$",
    )
):
    trends = BarberDatabaseManager.get_revenue_trends(
        period=period
    )

    return {
        "success": True,
        "period": period,
        "trends": trends,
    }


@router.get("/revenue-by-service")
def get_revenue_by_service(
    period: str = Query(
        default="month",
        pattern="^(today|week|month)$",
    )
):
    services = BarberDatabaseManager.get_revenue_by_service(
        period=period
    )

    return {
        "success": True,
        "period": period,
        "services": services,
    }


# ------------------------------------------------------------------
# AI INSIGHTS
# ------------------------------------------------------------------

@router.get("/ai-recommendations")
def get_ai_recommendations(
    period: str = Query(
        default="today",
        pattern="^(today|week|month)$",
    )
):
    recommendations = (
        BarberDatabaseManager.get_ai_recommendations(
            period=period
        )
    )

    return {
        "success": True,
        "period": period,
        "recommendations": recommendations,
    }


# ------------------------------------------------------------------
# BANK RECONCILIATION
# ------------------------------------------------------------------

@router.get("/bank-reconciliation")
def get_bank_reconciliation(
    period: str = Query(
        default="today",
        pattern="^(today|week|month)$",
    )
):
    reconciliation = (
        BarberDatabaseManager.get_bank_reconciliation(
            period=period
        )
    )

    return {
        "success": True,
        "period": period,
        "reconciliation": reconciliation,
    }


@router.post("/bank-reconciliation/upload")
async def upload_bank_statement(
    period: str = Query(
        default="month",
        pattern="^(today|week|month)$",
    ),
    file: UploadFile = File(...),
):
    try:
        file_bytes = await file.read()

        if not file_bytes:
            raise HTTPException(
                status_code=400,
                detail="The uploaded bank statement is empty.",
            )

        result = (
            SmartBankReconciliationManager.reconcile_statement(
                filename=file.filename or "statement",
                file_bytes=file_bytes,
                period=period,
            )
        )

        return result

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=(
                "Bank reconciliation failed: "
                f"{str(error)}"
            ),
        ) from error


# ------------------------------------------------------------------
# REPORTS
# ------------------------------------------------------------------

@router.get("/monthly-report")
def get_monthly_report():
    report = BarberDatabaseManager.get_monthly_report()

    return {
        "success": True,
        "report": report,
    }


@router.get("/monthly-report/pdf")
def download_monthly_report_pdf():
    try:
        file_path = (
            MonthlyReportGenerator.generate_monthly_pdf()
        )

        return FileResponse(
            path=file_path,
            media_type="application/pdf",
            filename=file_path.split("/")[-1],
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "Monthly PDF report generation failed: "
                f"{str(error)}"
            ),
        ) from error