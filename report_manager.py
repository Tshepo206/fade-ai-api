from monthly_report_generator import MonthlyReportGenerator


class ReportManager:
    @staticmethod
    def get_monthly_report(business_id: str) -> dict:
        from dashboard_analytics_manager import DashboardAnalyticsManager
        return DashboardAnalyticsManager.get_monthly_report(business_id)

    @staticmethod
    def generate_monthly_pdf(business_id: str, business_name: str = "GoodKeeper Workspace") -> str:
        return MonthlyReportGenerator.generate_monthly_pdf(business_id, business_name)
