### User
How many recipes contain both garlic and onion, and what percentage of all recipes is that?

### Bot
16,319 of 122,918 = 13.28%

--- RECEIPT ---
tool: stats.percentage
filters: contains ALL of: garlic, onion
dataset: 122,918 valid of 125,164 records (2,246 invalid, excluded)
analyzed: 122,918
denominator: 122,918 (all valid recipes)
formula: percentage = 100 * matching / denominator
normalization: form-aware token-sequence match on normalized names (aliases, singular forms); e.g. garlic powder is not counted as garlic; 'garlic' excludes items with: bread, chive, flake, oil, paste, powder...; 'onion' excludes items with: dip, flake, green, juice, powder, ring...
step rule: estimated instruction steps: newline-separated blocks if >=2 blocks, else sentences (ADVERTISEMENT/bare numbering removed; recipebot/steps.py)
valid = title non-blank AND >=1 clean ingredient line AND >=1 instruction step
duplicates: near-duplicate recipes (same title + ingredients, mostly across sources) are NOT removed; see docs/DATA_AUDIT.md section 4
sql: SELECT id FROM recipes WHERE is_valid=1
sql: SELECT i.recipe_id, i.canon, i.forms, i.alts FROM ingredients i JOIN recipes r ON r.id=i.recipe_id WHERE r.is_valid=1 AND i.canon LIKE '%garlic%' -- then form-aware match in Python
sql: SELECT i.recipe_id, i.canon, i.forms, i.alts FROM ingredients i JOIN recipes r ON r.id=i.recipe_id WHERE r.is_valid=1 AND i.canon LIKE '%onion%' -- then form-aware match in Python

_state: dish: - | include: - | exclude: - | restrictions: - | max_steps: - | available: - | preferences: - | focus: - | last_results: 0_