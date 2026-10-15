"""The fixed set of content niches a profile can be classified into.

One flat enum, not a hierarchy: a hierarchy needs training data and editorial
governance this PoC doesn't have, and a flat ~20-way choice is what a single
structured-output call can hold reliably. Real influencer-marketing platforms
(HypeAuditor, Modash) don't use a closed taxonomy at all — they do open
keyword/AI search over free-text labels. A closed list is a concession to
needing an LLM to pick exactly one category, not an industry standard being
followed here.
"""

from __future__ import annotations

from enum import Enum


class Category(str, Enum):
    FASHION_STYLE = "Fashion & Style"
    BEAUTY_SKINCARE = "Beauty & Skincare"
    FITNESS_HEALTH = "Fitness & Health"
    FOOD_COOKING = "Food & Cooking"
    TRAVEL = "Travel"
    TECH_GADGETS = "Technology & Gadgets"
    GAMING_ESPORTS = "Gaming & Esports"
    BUSINESS_FINANCE = "Business & Finance"
    PARENTING_FAMILY = "Parenting & Family"
    PETS_ANIMALS = "Pets & Animals"
    COMEDY_ENTERTAINMENT = "Comedy & Entertainment"
    MUSIC = "Music"
    ART_DESIGN = "Art & Design"
    EDUCATION = "Education & Learning"
    LIFESTYLE_VLOG = "Lifestyle & Vlogging"
    AUTOMOTIVE = "Automotive"
    SPORTS = "Sports"
    PHOTOGRAPHY = "Photography"
    HOME_INTERIOR = "Home & Interior Design"
    OTHER = "Other / Uncategorized"


CATEGORY_DESCRIPTIONS: dict[Category, str] = {
    Category.FASHION_STYLE: "Outfits, styling, fashion brands, model/editorial content.",
    Category.BEAUTY_SKINCARE: "Makeup, skincare routines, haircare, beauty product reviews.",
    Category.FITNESS_HEALTH: "Workouts, gym content, nutrition, physical wellness, body transformation.",
    Category.FOOD_COOKING: "Recipes, restaurant reviews, cooking tutorials, food photography.",
    Category.TRAVEL: "Destinations, travel guides, trip vlogs, hotel/flight content.",
    Category.TECH_GADGETS: "Consumer electronics, software, apps, product reviews, tech news.",
    Category.GAMING_ESPORTS: "Video games, streaming, esports, gaming gear.",
    Category.BUSINESS_FINANCE: "Entrepreneurship, investing, personal finance, career/business advice.",
    Category.PARENTING_FAMILY: "Family life, parenting tips, kids' content, pregnancy/motherhood.",
    Category.PETS_ANIMALS: "Pet accounts, animal care, wildlife content.",
    Category.COMEDY_ENTERTAINMENT: "Sketches, memes, pop culture commentary, general entertainment.",
    Category.MUSIC: "Musicians, singers, producers, music performance/reviews.",
    Category.ART_DESIGN: "Illustration, painting, graphic/product design, creative process content.",
    Category.EDUCATION: "Teaching, explainers, study content, academic/skill-building material.",
    Category.LIFESTYLE_VLOG: "Day-in-the-life, general personal vlogging that doesn't fit a narrower niche.",
    Category.AUTOMOTIVE: "Cars, motorcycles, car culture, reviews and builds.",
    Category.SPORTS: "Athletes, sports commentary, fandom content (distinct from personal fitness).",
    Category.PHOTOGRAPHY: "Photography as the subject itself (gear, technique, portfolio accounts).",
    Category.HOME_INTERIOR: "Interior design, home decor, renovation, organization content.",
    Category.OTHER: "Public figures, brands, or accounts that don't fit a content niche above.",
}
