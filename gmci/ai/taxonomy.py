"""Topic vocabulary shared by the offline analyser and the AI prompts.

Keeping AI output on a known topic list is what makes trend percentages meaningful: "Festive
offer", "Diwali Offer" and "Festival discount" all land on one topic. AI providers may still
propose a new topic when nothing fits; it is kept as-is.
"""

GENERIC = {
    "Festival Offer": ["diwali", "navratri", "ganesh", "holi", "christmas", "new year", "eid", "festive", "festival",
                       "dussehra", "raksha", "rakhi", "onam", "pongal", "independence day", "valentine"],
    "Discount & Promotion": ["% off", "discount", "flat", "offer", "deal", "save", "combo", "buy 1", "buy one",
                             "complimentary", "limited period", "limited time", "special price", "cashback"],
    "Customer Testimonial": ["review", "testimonial", "happy client", "happy customer", "thank you", "feedback",
                             "loved", "said", "stars", "5-star", "happy patient"],
    "New Service Launch": ["introducing", "launch", "now available", "new service", "newly", "now offering", "we now"],
    "Team Spotlight": ["meet our", "our team", "years of experience", "certified", "trained in", "mds", "senior stylist"],
    "Announcement & Timings": ["timings", "open on", "closed", "holiday", "hours", "now open", "relocated", "new branch",
                               "anniversary", "celebrating"],
    "Membership & Loyalty": ["membership", "member", "loyalty", "package", "prepaid", "card", "referral", "refer"],
    "Hygiene & Safety": ["hygiene", "sanitised", "sanitized", "sterilised", "sterilized", "disposable", "safety", "clean"],
    "Seasonal Care": ["monsoon", "summer", "winter", "humidity", "rain", "sun", "heat", "dry season"],
}

INDUSTRY = {
    "salon": {
        "Hair Care Tips": ["hair care", "hair fall", "frizz", "split ends", "dandruff", "oiling", "hair mask",
                           "shampoo", "conditioner", "scalp", "tips"],
        "Before/After Transformation": ["before/after", "before ➡", "before and after", "before & after", "transformation", "makeover", "glow up"],
        "Bridal Makeup": ["bridal", "bride", "wedding", "engagement", "sangeet", "mehendi", "trial"],
        "Hair Colour": ["colour", "color", "balayage", "highlights", "ombre", "global", "shade", "babylights"],
        "Keratin & Smoothening": ["keratin", "smoothening", "botox", "nanoplastia", "straightening", "rebonding", "cysteine"],
        "Skin Care & Facials": ["facial", "skin", "cleanup", "hydra", "glow", "tan", "acne", "d-tan", "peel"],
        "Men's Grooming": ["men", "beard", "fade", "gentlemen", "grooming", "shave", "groom"],
        "Nail Art": ["nail", "manicure", "pedicure", "gel", "extensions", "acrylic"],
        "Haircut & Styling": ["haircut", "hair cut", "layers", "bob", "styling", "blow dry", "curls", "bangs", "trim"],
    },
    "dental": {
        "Oral Hygiene Tips": ["brush", "floss", "oral hygiene", "plaque", "gum", "mouthwash", "tips", "cavity"],
        "Teeth Whitening": ["whitening", "white", "stain", "bleaching", "brighter smile"],
        "Aligners & Braces": ["aligner", "braces", "invisalign", "orthodontic", "crooked", "retainer"],
        "Dental Implants": ["implant", "missing teeth", "denture", "crown", "bridge"],
        "Kids Dentistry": ["kids", "children", "child", "milk teeth", "pediatric", "paediatric"],
        "Root Canal": ["root canal", "rct", "pain-free", "painless", "toothache"],
        "Free Check-up Camp": ["free check", "free dental", "camp", "screening", "consultation"],
        "Smile Makeover": ["smile makeover", "veneers", "smile design", "cosmetic"],
    },
    "restaurant": {
        "New Menu Item": ["new on the menu", "menu", "dish", "try our", "chef's special", "signature"],
        "Food Offer": ["meal", "thali", "buffet", "happy hour", "combo"],
        "Events & Live Music": ["live music", "event", "dj", "karaoke", "screening"],
        "Delivery & Takeaway": ["delivery", "zomato", "swiggy", "takeaway", "order online"],
    },
    "gym": {
        "Fitness Tips": ["workout", "exercise", "protein", "tips", "cardio", "stretch"],
        "Membership Offer": ["membership", "join", "trial", "joining fee"],
        "Transformation Story": ["transformation", "lost", "kg", "before/after", "before and after"],
        "Group Classes": ["zumba", "yoga", "hiit", "crossfit", "class", "batch"],
    },
}

CONTENT_TYPES = {
    "Offer / Promotion": ["% off", "discount", "flat ", "offer", "deal", "combo", "buy 1", "complimentary", "₹", " rs.", " rs "],
    "Educational Tip": ["tip", "did you know", "how to", "myth", "fact", "should you", "why ", "steps", "guide",
                        "recommend", "avoid", "difference", "here's what", "is not normal", "the best time", "explained"],
    "Before/After Showcase": ["before/after", "before ➡", "before and after", "transformation", "makeover"],
    "Testimonial": ["review", "testimonial", "happy client", "happy patient", "feedback", "thank you"],
    "Service Launch": ["introducing", "launch", "now available", "new service", "now offering"],
    "Event": ["event", "camp", "workshop", "masterclass", "live"],
    "Greeting": ["wishing", "wishes", "happy diwali", "happy new year", "merry", "greetings", "eid mubarak"],
    "Announcement": ["timings", "closed", "open", "holiday", "branch", "anniversary"],
    "Service Showcase": ["package", "menu", "available", "collection", "options", "slots", "we use", "trained"],
}

CTA_PATTERNS = {
    "Book appointment": ["book", "appointment", "reserve", "slot"],
    "Call now": ["call", "📞", "phone", "ring us"],
    "WhatsApp / DM": ["whatsapp", "dm", "message us", "direct message"],
    "Visit / Walk in": ["visit", "walk in", "walk-in", "drop by", "come in"],
    "Learn more": ["learn more", "know more", "link in", "read more"],
    "Claim offer": ["claim", "grab", "redeem", "avail", "get offer", "hurry"],
}


def topics_for(industry: str) -> dict:
    key = guess_industry_key(industry)
    merged = dict(INDUSTRY.get(key, {}))
    merged.update(GENERIC)
    return merged


def guess_industry_key(industry: str) -> str:
    text = (industry or "").lower()
    for key, words in {"salon": ["salon", "beauty", "hair", "spa", "parlour", "parlor"],
                       "dental": ["dental", "dentist", "teeth", "orthodont"],
                       "restaurant": ["restaurant", "cafe", "café", "food", "bakery", "bar"],
                       "gym": ["gym", "fitness", "yoga", "crossfit"]}.items():
        if any(w in text for w in words):
            return key
    return ""


# How the offline idea generator talks about a topic, and which content angles suit it.
SUBJECTS = {
    "Festival Offer": "festive looks", "Discount & Promotion": "best-value packages", "Customer Testimonial": "service",
    "New Service Launch": "new services", "Team Spotlight": "services", "Announcement & Timings": "visit planning",
    "Membership & Loyalty": "membership", "Hygiene & Safety": "hygiene standards", "Seasonal Care": "seasonal care",
    "Before/After Transformation": "transformation", "Hair Care Tips": "hair care", "Oral Hygiene Tips": "oral hygiene",
    "Fitness Tips": "fitness", "Free Check-up Camp": "dental check-ups", "Transformation Story": "transformation",
}
ANGLE_FIT = {
    "Festival Offer": {"offer", "checklist", "launch"},
    "Discount & Promotion": {"offer", "compare"},
    "Customer Testimonial": {"testimonial"},
    "Team Spotlight": {"team"},
    "Announcement & Timings": set(),
    "New Service Launch": {"faq", "first"},
    "Membership & Loyalty": {"launch", "faq", "compare", "offer"},
    "Hygiene & Safety": {"behind", "faq", "myth"},
    "Seasonal Care": {"tips", "checklist", "myth", "offer"},
    "Before/After Transformation": {"showcase"},
    "Transformation Story": {"showcase"},
    "Free Check-up Camp": {"launch", "faq", "first", "offer"},
}
