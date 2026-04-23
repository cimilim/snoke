from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MealItem:
    id: str
    name: str
    kcal_per_portion: int
    portion_label: str
    category: str
    protein_g: float
    fat_g: float
    carb_g: float
    is_healthy_alternative: bool = False
    source: str = "default"


def estimate_macros_from_kcal(
    kcal: int,
    *,
    protein_share: float = 0.20,
    fat_share: float = 0.30,
) -> tuple[float, float, float]:
    """Rough macro split for fallback/manual entries.

    carbs share is inferred from remaining calories.
    """
    kcal_f = max(1.0, float(kcal))
    p_kcal = kcal_f * protein_share
    f_kcal = kcal_f * fat_share
    c_kcal = max(0.0, kcal_f - p_kcal - f_kcal)
    return (round(p_kcal / 4.0, 1), round(f_kcal / 9.0, 1), round(c_kcal / 4.0, 1))


def _meal(
    meal_id: str,
    name: str,
    kcal: int,
    portion_label: str,
    category: str,
    *,
    protein_g: float | None = None,
    fat_g: float | None = None,
    carb_g: float | None = None,
    healthy: bool = False,
) -> MealItem:
    if protein_g is None or fat_g is None or carb_g is None:
        p, f, c = estimate_macros_from_kcal(kcal)
        protein_g = p if protein_g is None else protein_g
        fat_g = f if fat_g is None else fat_g
        carb_g = c if carb_g is None else carb_g
    return MealItem(
        id=meal_id,
        name=name,
        kcal_per_portion=kcal,
        portion_label=portion_label,
        category=category,
        protein_g=float(protein_g),
        fat_g=float(fat_g),
        carb_g=float(carb_g),
        is_healthy_alternative=healthy,
    )


DEFAULT_MEALS: list[MealItem] = [
    _meal("meal-001", "Spaghetti Bolognese", 680, "1 Teller", "Pasta"),
    _meal("meal-002", "Lasagne", 760, "1 Portion", "Pasta"),
    _meal("meal-003", "Penne Arrabbiata", 620, "1 Teller", "Pasta"),
    _meal("meal-004", "Pizza Margherita", 800, "1 Pizza", "Pizza"),
    _meal("meal-005", "Pizza Salami", 980, "1 Pizza", "Pizza"),
    _meal("meal-006", "Pizza Tonno", 920, "1 Pizza", "Pizza"),
    _meal("meal-007", "Döner Kebab", 700, "1 Döner", "Fast Food"),
    _meal("meal-008", "Dürüm", 760, "1 Dürüm", "Fast Food"),
    _meal("meal-009", "Cheeseburger", 520, "1 Burger", "Fast Food"),
    _meal("meal-010", "Pommes", 430, "1 Portion", "Fast Food"),
    _meal("meal-011", "Chicken Nuggets", 450, "9 Stück", "Fast Food"),
    _meal("meal-012", "Currywurst mit Pommes", 900, "1 Portion", "Fast Food"),
    _meal("meal-013", "Schnitzel mit Pommes", 980, "1 Teller", "Klassisch"),
    _meal("meal-014", "Bratwurst mit Kartoffelsalat", 760, "1 Teller", "Klassisch"),
    _meal("meal-015", "Rinderroulade mit Klößen", 840, "1 Teller", "Klassisch"),
    _meal("meal-016", "Hähnchenbrust mit Reis", 620, "1 Teller", "Fitness", protein_g=42, fat_g=16, carb_g=62),
    _meal("meal-017", "Lachs mit Ofengemüse", 680, "1 Teller", "Fitness", protein_g=38, fat_g=36, carb_g=38),
    _meal("meal-018", "Reispfanne mit Gemüse", 560, "1 Teller", "Vegetarisch"),
    _meal("meal-019", "Gemüse-Curry mit Reis", 640, "1 Teller", "Vegetarisch"),
    _meal("meal-020", "Falafel-Teller", 720, "1 Teller", "Vegetarisch"),
    _meal("meal-021", "Chili con Carne", 610, "1 Schale", "Eintopf"),
    _meal("meal-022", "Linsensuppe", 420, "1 Schale", "Eintopf"),
    _meal("meal-023", "Erbsensuppe", 480, "1 Schale", "Eintopf"),
    _meal("meal-024", "Müsli mit Milch", 430, "1 Schale", "Frühstück"),
    _meal("meal-025", "Overnight Oats", 390, "1 Glas", "Frühstück"),
    _meal("meal-026", "Rührei mit Brot", 460, "1 Portion", "Frühstück"),
    _meal("meal-027", "Croissant", 260, "1 Stück", "Frühstück"),
    _meal("meal-028", "Brezel", 230, "1 Stück", "Snack"),
    _meal("meal-029", "Käsebrötchen", 340, "1 Stück", "Snack"),
    _meal("meal-030", "Thunfisch-Sandwich", 420, "1 Stück", "Snack"),
    _meal("meal-031", "Caesar Salad", 510, "1 Schüssel", "Salat"),
    _meal("meal-032", "Gemischter Salat mit Feta", 420, "1 Schüssel", "Salat"),
    _meal("meal-033", "Burrito Bowl", 740, "1 Schüssel", "Bowl"),
    _meal("meal-034", "Poke Bowl Lachs", 690, "1 Schüssel", "Bowl"),
    _meal("meal-035", "Sushi (12 Stück)", 520, "1 Box", "Asiatisch"),
    _meal("meal-036", "Gebratene Nudeln mit Huhn", 770, "1 Box", "Asiatisch"),
    _meal("meal-037", "Gebratener Reis mit Gemüse", 650, "1 Box", "Asiatisch"),
    _meal("meal-038", "Pad Thai", 780, "1 Teller", "Asiatisch"),
    _meal("meal-039", "Käsespätzle", 890, "1 Teller", "Klassisch"),
    _meal("meal-040", "Kartoffelgratin", 540, "1 Portion", "Beilage"),
    _meal("meal-041", "Ofenkartoffel mit Kräuterquark", 520, "1 Portion", "Vegetarisch"),
    _meal("meal-042", "Proteinshake", 220, "1 Shake", "Drink", protein_g=30, fat_g=4, carb_g=12),
    _meal("meal-043", "Cappuccino mit Zucker", 120, "1 Tasse", "Drink"),
    _meal("meal-044", "Latte Macchiato", 190, "1 Glas", "Drink"),
    _meal("meal-045", "Apfel", 95, "1 Stück", "Snack", protein_g=0.4, fat_g=0.2, carb_g=25),
    _meal("meal-046", "Banane", 105, "1 Stück", "Snack", protein_g=1.2, fat_g=0.3, carb_g=27),
    _meal("meal-047", "Naturjoghurt mit Honig", 230, "1 Becher", "Snack", protein_g=11, fat_g=6, carb_g=31),
    _meal("meal-048", "Quark mit Beeren", 280, "1 Schale", "Snack", protein_g=25, fat_g=4, carb_g=28),
    _meal("meal-049", "Schokolade", 250, "50 g", "Snack"),
    _meal("meal-050", "Nüsse gemischt", 300, "50 g", "Snack", protein_g=9, fat_g=27, carb_g=8),
    # Healthy alternatives
    _meal("meal-051", "Skyr mit Haferflocken und Beeren", 390, "1 Schale", "Healthy", protein_g=30, fat_g=7, carb_g=52, healthy=True),
    _meal("meal-052", "Magerquark-Bowl mit Banane", 360, "1 Schale", "Healthy", protein_g=36, fat_g=3, carb_g=42, healthy=True),
    _meal("meal-053", "Griechischer Joghurt 2% mit Nüssen", 340, "1 Schale", "Healthy", protein_g=22, fat_g=15, carb_g=25, healthy=True),
    _meal("meal-054", "Hähnchen, Reis und Brokkoli", 610, "1 Teller", "Healthy", protein_g=46, fat_g=14, carb_g=70, healthy=True),
    _meal("meal-055", "Linsen-Bowl mit Feta", 520, "1 Schüssel", "Healthy", protein_g=26, fat_g=17, carb_g=59, healthy=True),
    _meal("meal-056", "Tofu-Gemüse-Pfanne", 480, "1 Teller", "Healthy", protein_g=28, fat_g=19, carb_g=45, healthy=True),
    _meal("meal-057", "Vollkornbrot mit Hüttenkäse", 310, "2 Scheiben", "Healthy", protein_g=22, fat_g=6, carb_g=43, healthy=True),
    _meal("meal-058", "Lachs-Salat-Bowl", 560, "1 Schüssel", "Healthy", protein_g=34, fat_g=31, carb_g=24, healthy=True),
    _meal("meal-059", "Haferflocken mit Whey", 420, "1 Schale", "Healthy", protein_g=34, fat_g=8, carb_g=50, healthy=True),
    _meal("meal-060", "Eier-Avocado-Vollkorn-Toast", 430, "1 Portion", "Healthy", protein_g=21, fat_g=22, carb_g=36, healthy=True),
]

