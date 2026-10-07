"""Reference pools used to generate synthetic customers, addresses and products.

Everything here is fictional. Emails use the reserved example.com domain.
"""

FIRST_NAMES = [
    "Aiden", "Amara", "Anika", "Arjun", "Beatrice", "Caleb", "Camila", "Dario", "Elena", "Elias",
    "Farah", "Felix", "Grace", "Hana", "Hugo", "Imani", "Isla", "Jonas", "Kavya", "Kofi",
    "Lena", "Liam", "Maya", "Mateo", "Nadia", "Noah", "Olivia", "Omar", "Priya", "Quinn",
    "Rafael", "Rhea", "Sana", "Soren", "Talia", "Theo", "Uma", "Victor", "Willa", "Zane",
]

LAST_NAMES = [
    "Abbott", "Banerjee", "Calloway", "Delgado", "Eriksen", "Fairweather", "Gallagher", "Hartwell",
    "Iyer", "Jankowski", "Kowalski", "Lindqvist", "Marchetti", "Nakamura", "Okafor", "Pemberton",
    "Quintero", "Rasmussen", "Sandoval", "Thornton", "Underwood", "Vasquez", "Whitfield", "Xiong",
    "Yamada", "Zielinski", "Ashworth", "Brennan", "Castellano", "Dunmore", "Ellison", "Fontaine",
    "Granger", "Holloway", "Ibarra", "Jorgensen", "Kingsley", "Larkin", "Montague", "Nightingale",
]

STREET_NAMES = [
    "Cedar", "Maple", "Juniper", "Willow", "Aspen", "Birch", "Alder", "Hickory", "Spruce", "Laurel",
    "Summit", "Ridge", "Meadow", "Harbor", "Prairie", "Canyon", "Orchard", "Lakeview", "Sunset", "Granite",
]
STREET_TYPES = ["Lane", "Street", "Avenue", "Road", "Court", "Drive", "Way"]

CITIES = [
    "Portland", "Denver", "Boise", "Madison", "Burlington", "Asheville", "Duluth", "Spokane",
    "Salt Lake City", "Albuquerque", "Missoula", "Flagstaff", "Bend", "Chattanooga", "Anchorage",
]

# (category, product types, price range in whole dollars (min, max), item count, sizing)
CATALOGUE_SPEC = [
    ("jackets",       ["Shell Jacket", "Insulated Jacket", "Rain Jacket", "Windbreaker", "Parka"], (90, 320), 8, "apparel"),
    ("fleece",        ["Fleece Pullover", "Fleece Vest", "Fleece Jacket", "Quarter-Zip"],          (45, 130), 6, "apparel"),
    ("base_layers",   ["Base Layer Top", "Base Layer Bottom", "Thermal Tee", "Merino Crew"],       (30, 95),  6, "apparel"),
    ("pants",         ["Hiking Pants", "Trail Shorts", "Softshell Pants", "Convertible Pants"],    (45, 140), 8, "apparel"),
    ("footwear",      ["Trail Runner", "Hiking Boot", "Approach Shoe", "Camp Sandal"],             (70, 220), 8, "footwear"),
    ("packs",         ["Daypack", "Trekking Pack", "Hydration Pack", "Duffel"],                    (50, 260), 6, "none"),
    ("tents",         ["Backpacking Tent", "Family Tent", "Bivy Shelter"],                         (150, 480), 4, "none"),
    ("sleeping_bags", ["Down Sleeping Bag", "Synthetic Sleeping Bag", "Quilt"],                    (90, 380), 4, "none"),
    ("accessories",   ["Insulated Bottle", "Headlamp", "Trekking Poles", "Wool Beanie", "Gloves",
                       "Camp Stove", "Cookset", "Dry Bag", "Trail Socks", "Sun Hat"],              (10, 90),  10, "none"),
]

PRODUCT_ADJECTIVES = [
    "Alpine", "Summit", "Ridgeline", "Canyon", "Glacier", "Timberline", "Trailhead", "Backcountry",
    "Evergreen", "Cascade", "Highland", "Tundra", "Basecamp", "Sierra", "Northfork", "Ironwood",
]

SIZES = {
    "apparel": ["XS", "S", "M", "L", "XL", "XXL"],
    "footwear": ["7", "8", "9", "10", "11", "12", "13"],
    "none": [],
}

CARRIERS = ["SwiftShip", "TrailExpress", "MeridianPost"]


CATEGORY_SIZING = {category: sizing for category, _t, _p, _n, sizing in CATALOGUE_SPEC}
