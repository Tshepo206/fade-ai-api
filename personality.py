import random


def get_time_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def get_opening_line(day_of_week: str, time_of_day: str) -> str:
    day = (day_of_week or "").lower()
    time = (time_of_day or "").lower()

    day_lines = {
        "monday": [
            "☕ Monday... let's start the week looking sharp.",
            "💪 New week, new haircut?",
            "😄 Mondays are easier after a fresh fade."
        ],
        "tuesday": [
            "😎 Tuesday is a good day to beat the weekend rush.",
            "💈 A fresh cut today means less stress later."
        ],
        "wednesday": [
            "🔥 Halfway through the week already!",
            "✂️ Midweek maintenance never hurt anybody."
        ],
        "thursday": [
            "😄 Thursday is basically Friday's warm-up.",
            "💈 Beat tomorrow's rush and book today."
        ],
        "friday": [
            "🎉 Friday! Looking sharp for the weekend starts here.",
            "😎 Weekend plans deserve a fresh haircut."
        ],
        "saturday": [
            "🔥 Saturdays are made for fresh fades.",
            "☕ Coffee. Haircut. Weekend. Perfect combo."
        ],
        "sunday": [
            "😌 Self-care Sunday starts with a fresh cut.",
            "🌞 A good haircut is a great way to prepare for the week."
        ]
    }

    time_lines = {
        "morning": [
            "☕ Morning! Let's get your haircut sorted.",
            "🌅 Good morning! The barber is ready."
        ],
        "afternoon": [
            "😎 Afternoon! Still plenty of time to look fresh.",
            "💈 Afternoon bookings are looking good."
        ],
        "evening": [
            "🌙 Good evening! Let's get you booked.",
            "✂️ Evening plans? A fresh haircut always helps."
        ],
        "night": [
            "🌙 Late one! Let's get your booking sorted.",
            "😄 Even at night, a fresh cut still matters."
        ]
    }

    options = []

    if day in day_lines:
        options.extend(day_lines[day])

    if time in time_lines:
        options.extend(time_lines[time])

    if not options:
        options = [
            "💈 Looking sharp never goes out of style.",
            "🔥 Let's get you cleaned up and looking fresh.",
            "😄 A fresh cut will not solve everything, but it definitely helps."
        ]

    return random.choice(options)