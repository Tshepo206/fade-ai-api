from datetime import datetime, timedelta

from fastapi import APIRouter, Query, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from db_manager import BarberDatabaseManager
from monthly_report_generator import MonthlyReportGenerator
from bank_reconciliation import SmartBankReconciliationManager


router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
)


class BlockSlotRequest(BaseModel):
    start_datetime: str
    end_datetime: str
    reason: str = "Dashboard manual block"


@router.get("/summary")
def get_dashboard_summary(
    period: str = Query(default="today", pattern="^(today|week|month)$")
):
    return BarberDatabaseManager.get_dashboard_summary(period)


@router.get("/bookings")
def get_dashboard_bookings(limit: int = Query(default=20, ge=1, le=100)):
    bookings = BarberDatabaseManager.get_upcoming_bookings(limit=limit)

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


@router.get("/transactions")
def get_dashboard_transactions(limit: int = Query(default=20, ge=1, le=500)):
    transactions = BarberDatabaseManager.get_recent_transactions(limit=limit)

    return {
        "success": True,
        "count": len(transactions),
        "transactions": transactions,
    }


@router.get("/calendar")
def get_dashboard_calendar(
    view: str = Query(default="day", pattern="^(day|week|month)$"),
    target_date: str = Query(default=None),
):
    if target_date:
        start_date = datetime.fromisoformat(target_date)
    else:
        start_date = datetime.now()

    if view == "day":
        start_dt = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(days=1)

    elif view == "week":
        start_dt = start_date - timedelta(days=start_date.weekday())
        start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(days=7)

    else:
        start_dt = start_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        if start_dt.month == 12:
            end_dt = start_dt.replace(year=start_dt.year + 1, month=1)
        else:
            end_dt = start_dt.replace(month=start_dt.month + 1)

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
def block_calendar_time(payload: BlockSlotRequest):
    success = BarberDatabaseManager.block_time_range(
        start_datetime=payload.start_datetime,
        end_datetime=payload.end_datetime,
        reason=payload.reason or "Blocked time",
    )

    return {
        "success": success,
        "message": "Time blocked successfully" if success else "Could not block time",
    }


@router.delete("/calendar/unblock/{slot_id}")
def unblock_calendar_slot(slot_id: int):
    success = BarberDatabaseManager.unblock_slot(slot_id)

    return {
        "success": success,
        "message": "Slot unblocked successfully" if success else "Could not unblock slot",
    }


@router.get("/revenue-trends")
def get_revenue_trends(period: str = Query(default="week", pattern="^(week|month)$")):
    trends = BarberDatabaseManager.get_revenue_trends(period=period)

    return {
        "success": True,
        "period": period,
        "trends": trends,
    }


@router.get("/revenue-by-service")
def get_revenue_by_service(
    period: str = Query(default="month", pattern="^(today|week|month)$")
):
    services = BarberDatabaseManager.get_revenue_by_service(period=period)

    return {
        "success": True,
        "period": period,
        "services": services,
    }


@router.get("/top-customers")
def get_top_customers(
    period: str = Query(default="month", pattern="^(week|month|all)$"),
    limit: int = Query(default=10, ge=1, le=50),
):
    customers = BarberDatabaseManager.get_top_customers(period=period, limit=limit)

    return {
        "success": True,
        "period": period,
        "count": len(customers),
        "customers": customers,
    }


@router.get("/ai-recommendations")
def get_ai_recommendations(
    period: str = Query(default="today", pattern="^(today|week|month)$")
):
    recommendations = BarberDatabaseManager.get_ai_recommendations(period=period)

    return {
        "success": True,
        "period": period,
        "recommendations": recommendations,
    }


@router.get("/bank-reconciliation")
def get_bank_reconciliation(
    period: str = Query(default="today", pattern="^(today|week|month)$")
):
    reconciliation = BarberDatabaseManager.get_bank_reconciliation(period=period)

    return {
        "success": True,
        "period": period,
        "reconciliation": reconciliation,
    }


@router.post("/bank-reconciliation/upload")
async def upload_bank_statement(
    period: str = Query(default="month", pattern="^(today|week|month)$"),
    file: UploadFile = File(...),
):
    try:
        file_bytes = await file.read()

        result = SmartBankReconciliationManager.reconcile_statement(
            filename=file.filename or "statement",
            file_bytes=file_bytes,
            period=period,
        )

        return result

    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=f"Bank reconciliation failed: {str(error)}",
        )


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
        file_path = MonthlyReportGenerator.generate_monthly_pdf()

        return FileResponse(
            path=file_path,
            media_type="application/pdf",
            filename=file_path.split("/")[-1],
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Monthly PDF report generation failed: {str(error)}",
        )