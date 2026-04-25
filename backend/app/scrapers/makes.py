"""Centralized target configuration for auction scraping platforms.

BaT exposes make/model archive pages, so we retain make slugs as crawl seeds.
Cars & Bids is crawled through the global closed-auctions feed and deliberately
does not depend on a hand-written make/model list.
"""

# ---------------------------------------------------------------------------
# Bring a Trailer — lowercase hyphenated make slugs
# ---------------------------------------------------------------------------

BAT_MAKES: list[tuple[str, str, str]] = [
    ("acura", "Acura", "acura"),
    ("alfa-romeo", "Alfa Romeo", "alfa-romeo"),
    ("aston-martin", "Aston Martin", "aston-martin"),
    ("audi", "Audi", "audi"),
    ("bentley", "Bentley", "bentley"),
    ("bmw", "BMW", "bmw"),
    ("bugatti", "Bugatti", "bugatti"),
    ("buick", "Buick", "buick"),
    ("cadillac", "Cadillac", "cadillac"),
    ("chevrolet", "Chevrolet", "chevrolet"),
    ("chrysler", "Chrysler", "chrysler"),
    ("dodge", "Dodge", "dodge"),
    ("ferrari", "Ferrari", "ferrari"),
    ("fiat", "Fiat", "fiat"),
    ("ford", "Ford", "ford"),
    ("genesis", "Genesis", "genesis"),
    ("gmc", "GMC", "gmc"),
    ("honda", "Honda", "honda"),
    ("hyundai", "Hyundai", "hyundai"),
    ("infiniti", "Infiniti", "infiniti"),
    ("jaguar", "Jaguar", "jaguar"),
    ("jeep", "Jeep", "jeep"),
    ("kia", "Kia", "kia"),
    ("lamborghini", "Lamborghini", "lamborghini"),
    ("land-rover", "Land Rover", "land-rover"),
    ("lexus", "Lexus", "lexus"),
    ("lincoln", "Lincoln", "lincoln"),
    ("lotus", "Lotus", "lotus"),
    ("maserati", "Maserati", "maserati"),
    ("mazda", "Mazda", "mazda"),
    ("mclaren", "McLaren", "mclaren"),
    ("mercedes-benz", "Mercedes-Benz", "mercedes-benz"),
    ("mini", "MINI", "mini"),
    ("mitsubishi", "Mitsubishi", "mitsubishi"),
    ("nissan", "Nissan", "nissan"),
    ("pagani", "Pagani", "pagani"),
    ("porsche", "Porsche", "porsche"),
    ("ram", "Ram", "ram"),
    ("rolls-royce", "Rolls-Royce", "rolls-royce"),
    ("subaru", "Subaru", "subaru"),
    ("tesla", "Tesla", "tesla"),
    ("toyota", "Toyota", "toyota"),
    ("volkswagen", "Volkswagen", "volkswagen"),
    ("volvo", "Volvo", "volvo"),
]
