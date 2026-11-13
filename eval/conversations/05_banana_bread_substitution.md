### User
Find banana bread

### Bot
287 recipes passed all filters (of 287 retrieved candidates); showing 10:
 1. ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC  Banana Banana Bread  [3 steps, 7 ingredients]
 2. ar:zPU0I27hBx09bNpfvQEjNTyHl/X7uwK  Healthier Banana Banana Bread  [3 steps, 8 ingredients]
 3. ar:BoBTO3QUO3Ci.0kayPs8.CfDU5oEXuu  Banana Bread  [3 steps, 7 ingredients]
 4. ar:LCKlIJX8Jjf51FQPJqTQGydT1/m4zRi  Country Banana Bread  [3 steps, 4 ingredients]
 5. ar:c7DonAWp3sg843C9Gd4NmmcKoKJ6AU2  Banana Bread - Quick Bread for Machines  [3 steps, 7 ingredients]
 6. ar:UjSIU5jPRV5y/YJCWBBEZEueR7O3EAO  Simple Banana Bread  [4 steps, 7 ingredients]
 7. ar:pW/G7uT3a0khPJWk/AzOieElj4cz2ku  The Best Banana Bread  [3 steps, 6 ingredients]
 8. ar:/tgLkKTWsLuZ95S0LSm4WrrYcwKFuMi  Banana Oat Bread Pudding  [4 steps, 7 ingredients]
 9. ar:5S4TJwjeeH.L/gDoUxUR0jfxC/8Vd4u  Microwave Tofu Banana Bread  [3 steps, 4 ingredients]
10. ar:TJFqS5qmSUVcBw7c2Da99BzhmvnbgCm  Rich and Delicious Banana Bread  [3 steps, 6 ingredients]

--- RECEIPT ---
tool: search
filters: text query: 'banana bread'
dataset: 122,918 valid of 125,164 records (2,246 invalid, excluded)
retrieval: FTS5 BM25 (title weight 5x), query mode AND, top 300; vector index not built -> BM25 only
ordering: BM25 score ascending (best first), ties by id
normalization: form-aware token-sequence match on normalized names (aliases, singular forms); e.g. garlic powder is not counted as garlic
step rule: estimated instruction steps: newline-separated blocks if >=2 blocks, else sentences (ADVERTISEMENT/bare numbering removed; recipebot/steps.py)
candidates: 287
dropped by filters: none
valid = title non-blank AND >=1 clean ingredient line AND >=1 instruction step
duplicates: near-duplicate recipes (same title + ingredients, mostly across sources) are NOT removed; see docs/DATA_AUDIT.md section 4
recipe ids: ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC, ar:zPU0I27hBx09bNpfvQEjNTyHl/X7uwK, ar:BoBTO3QUO3Ci.0kayPs8.CfDU5oEXuu, ar:LCKlIJX8Jjf51FQPJqTQGydT1/m4zRi, ar:c7DonAWp3sg843C9Gd4NmmcKoKJ6AU2, ar:UjSIU5jPRV5y/YJCWBBEZEueR7O3EAO, ar:pW/G7uT3a0khPJWk/AzOieElj4cz2ku, ar:/tgLkKTWsLuZ95S0LSm4WrrYcwKFuMi, ar:5S4TJwjeeH.L/gDoUxUR0jfxC/8Vd4u, ar:TJFqS5qmSUVcBw7c2Da99BzhmvnbgCm
sql: SELECT r.id, bm25(recipes_fts, 5.0, 1.0) AS score FROM recipes_fts JOIN recipes r ON r.rowid = recipes_fts.rowid WHERE recipes_fts MATCH ? ORDER BY score, r.id LIMIT ?

_state: dish: banana bread | include: - | exclude: - | restrictions: - | max_steps: - | available: - | preferences: - | focus: - | last_results: 10_

---

### User
Replace the eggs in the first one

### Bot
SUBSTITUTE 'egg' in ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC  Banana Banana Bread
target lines: 5: '2 eggs, beaten'
roles of the target (config/roles.yaml): binder, moisture, leavening, richness
cohort: 118 similar recipes (108 contain egg, 10 do not; 96 same-dish, 22 same-class related)
EVIDENCE GRADE: moderate  -- 4/10 without vs 15/108 with (lift 2.9); below the strong thresholds or margin
candidates (dataset-mined, role-compatible; n/10 recipes WITHOUT egg use it | n/108 WITH it | lift):
  1. buttermilk         4/10 = 40% | 15/108 = 13.9% | lift 2.88  [moderate]  typical amount in these recipes 1 5/8 cup (n=4; shown for information)
       ids: fn:54fIX.3BAEv6ldUvjuy26bUDml2ljeG, ar:NDPVLC5JKV1rT1BciAqLCUl.sTnsydG, ar:UwdLINZCcxmNiOHXp2dXc9IxDXO8.ie, fn:mtvRCQS9rHf53TPLav3jNTvyugtW0wK
not offered (already in this recipe): banana, baking soda

RESULT: buttermilk (evidence grade moderate)
  line 5: replace '2 eggs, beaten' -> 'buttermilk'   [amount NOT inserted: similar recipes typically use 1 5/8 cup (median of 4), but that is not comparable to the removed line; set the quantity yourself]

UPDATED INGREDIENTS (edit applied by code):
   1. 2 cups all-purpose flour
   2. 1 teaspoon baking soda
   3. 1/4 teaspoon salt
   4. 1/2 cup butter
   5. 3/4 cup brown sugar
   6. buttermilk   <- changed
   7. 2 1/3 cups mashed overripe bananas
predictions (not dataset evidence): none; add --draft (needs the LLM) for validated revised steps
(dataset evidence about similar recipes, not a tested conversion; not medical advice; labels and cross-contamination not verified)

--- RECEIPT ---
tool: substitute
filters: recipe = ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC (Banana Banana Bread); target = egg (role entry 'egg': binder, moisture, leavening, richness); cohort: valid recipes whose title shares >= 2 of the dish tokens ['banana', 'bread'] (same-dish, ingredient Jaccard >= 0.2) or the dish class ['bread'] (Jaccard >= 0.35); top 500 by similarity
dataset: 122,918 valid of 125,164 records (2,246 invalid, excluded)
analyzed: 118
denominator: 10 similar recipes WITHOUT the target (share_without = recipes using the candidate / 10); 108 similar recipes WITH it (share_with = / 108)
formula: lift = share_without / max(share_with, 0.05); candidate kept if used in >= 2 recipes without the target and lift >= 1.5. insufficient: < 3 without. indirect: < 8 without, < 4 same-dish without, or < 3 with (lift unreliable). conflicting: top two within 20% (relative). strong: leader, share >= 0.25, lift >= 2.0, support >= 5, runner-up <= 0.70 x leader. moderate: share >= 0.15, lift >= 1.5, support >= 2. weak: otherwise. omission: share >= 0.5, graded at most moderate. Thresholds: config/roles.yaml
ordering: candidates by share_without desc, lift desc, support desc, name; supporting ids = most similar cohort recipes first
normalization: form-aware ingredient matching (normalize.matcher); role-compatible candidates only (config/roles.yaml can_fill)
candidates: 1
dropped by filters: below support/lift=19, blocked by restrictions=0, uncertain (possible)=0
valid = title non-blank AND >=1 clean ingredient line AND >=1 instruction step
duplicates: near-duplicate recipes (same title + ingredients, mostly across sources) are NOT removed; see docs/DATA_AUDIT.md section 4
recipe ids: ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC, fn:54fIX.3BAEv6ldUvjuy26bUDml2ljeG, ar:NDPVLC5JKV1rT1BciAqLCUl.sTnsydG, ar:UwdLINZCcxmNiOHXp2dXc9IxDXO8.ie, fn:mtvRCQS9rHf53TPLav3jNTvyugtW0wK
sql: SELECT id, title FROM recipes WHERE is_valid=1 AND (title LIKE '%<dish token>%' OR ...)
sql: SELECT recipe_id,pos,raw,canon,forms,alts,qty,unit FROM ingredients WHERE recipe_id IN (<pool ids>) ORDER BY recipe_id,pos

_state: dish: banana bread | include: - | exclude: - | restrictions: - | max_steps: - | available: - | preferences: - | focus: ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC | last_results: 10_

---

### User
Replace the butter in the first one

### Bot
SUBSTITUTE 'butter' in ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC  Banana Banana Bread
target lines: 3: '1/2 cup butter'
roles of the target (config/roles.yaml): fat, flavor, tenderness, moisture
cohort: 164 similar recipes (89 contain butter, 75 do not; 131 same-dish, 33 same-class related)
EVIDENCE GRADE: strong  -- 26/75 similar recipes without the target use it vs 8/89 with it (lift 3.9), clear margin over the runner-up
candidates (dataset-mined, role-compatible; n/75 recipes WITHOUT butter use it | n/89 WITH it | lift):
  1. vegetable oil      26/75 = 34.7% | 8/89 = 9% | lift 3.86  [strong]  typical amount in these recipes 1/2 cup (n=21; shown for information)
       ids: ar:n00vMomvPVPS6W2v.YjILBEpIKSMnfC, ar:xVwGx.rcpmdvNAKOI4BFp3Sdz9u0lee, epi:UItyt7rFkeOPnI.6KtaclLDviM19Sxa, fn:z42Y/QGo9vUN//syw4WSM7kTKlD.mfC, ar:XMHjFz7piZAIPzA4nNG7YumaOW7BEFe
  2. shortening         14/75 = 18.7% | 2/89 = 2.2% | lift 3.73  [conflicting]  typical amount in these recipes 1/2 cup (n=14; shown for information)
       ids: ar:6lWx3Z7kdt53H0U.oEsv2/Y2zai/VDC, fn:BIEftR0x3pSBQoGJfMqerctd6vykxw6, ar:V83CkKa.mEZI7F4JEs0sI95il5DRAOW, ar:XJWOjKCDEx4eugC9Dt/0P9jYx9Zt6kC, ar:bKFIjh7zd5pF0GR.vrJz9vvNknzLKGi
  3. margarine          12/75 = 16% | 0/89 = 0% | lift 3.2  [conflicting]  typical amount in these recipes 1/2 cup (n=9; shown for information)
       ids: ar:pW/G7uT3a0khPJWk/AzOieElj4cz2ku, ar:1SOVtYR.EsXlA6DdlIF8jYika3BGaZu, ar:cdiTXqrsbD9bI8aX4qRuiInvdHSwUtC, ar:Eg7xFHXmjE/UJ5URfRXV6YRDAt1VODS, ar:DcIUE5ijDjaMmoh59TJiyafZCvChIji
  4. canola oil         6/75 = 8% | 1/89 = 1.1% | lift 1.6  [weak]  typical amount in these recipes 1/3 cup (n=5; shown for information)
       ids: ar:T3Txy4pcITXm2Q4.MCAjpDynmXQjHQS, fn:b5i1LSfxSbfGsnmEJyZOwTBloH.5eb., ar:5TZm./2SXw01t7xgqse8yet6GH13IZm, ar:vqwhT7l74CGVrQZ3tGYEWDyFj.qJDYu, fn:voswl6jUhRyLDFVazv5g9NXhtV1ItsS
not offered (already in this recipe): banana

RESULT: vegetable oil (evidence grade strong)
  line 3: replace '1/2 cup butter' -> 'vegetable oil'   [amount NOT inserted: similar recipes typically use 1/2 cup (median of 21), but that is not comparable to the removed line; set the quantity yourself]

UPDATED INGREDIENTS (edit applied by code):
   1. 2 cups all-purpose flour
   2. 1 teaspoon baking soda
   3. 1/4 teaspoon salt
   4. vegetable oil   <- changed
   5. 3/4 cup brown sugar
   6. 2 eggs, beaten
   7. 2 1/3 cups mashed overripe bananas
predictions (not dataset evidence): none; add --draft (needs the LLM) for validated revised steps
(dataset evidence about similar recipes, not a tested conversion; not medical advice; labels and cross-contamination not verified)

--- RECEIPT ---
tool: substitute
filters: recipe = ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC (Banana Banana Bread); target = butter (role entry 'butter': fat, flavor, tenderness, moisture); cohort: valid recipes whose title shares >= 2 of the dish tokens ['banana', 'bread'] (same-dish, ingredient Jaccard >= 0.2) or the dish class ['bread'] (Jaccard >= 0.35); top 500 by similarity
dataset: 122,918 valid of 125,164 records (2,246 invalid, excluded)
analyzed: 164
denominator: 75 similar recipes WITHOUT the target (share_without = recipes using the candidate / 75); 89 similar recipes WITH it (share_with = / 89)
formula: lift = share_without / max(share_with, 0.05); candidate kept if used in >= 2 recipes without the target and lift >= 1.5. insufficient: < 3 without. indirect: < 8 without, < 4 same-dish without, or < 3 with (lift unreliable). conflicting: top two within 20% (relative). strong: leader, share >= 0.25, lift >= 2.0, support >= 5, runner-up <= 0.70 x leader. moderate: share >= 0.15, lift >= 1.5, support >= 2. weak: otherwise. omission: share >= 0.5, graded at most moderate. Thresholds: config/roles.yaml
ordering: candidates by share_without desc, lift desc, support desc, name; supporting ids = most similar cohort recipes first
normalization: form-aware ingredient matching (normalize.matcher); role-compatible candidates only (config/roles.yaml can_fill)
candidates: 4
dropped by filters: below support/lift=12, blocked by restrictions=0, uncertain (possible)=0
valid = title non-blank AND >=1 clean ingredient line AND >=1 instruction step
duplicates: near-duplicate recipes (same title + ingredients, mostly across sources) are NOT removed; see docs/DATA_AUDIT.md section 4
recipe ids: ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC, ar:n00vMomvPVPS6W2v.YjILBEpIKSMnfC, ar:xVwGx.rcpmdvNAKOI4BFp3Sdz9u0lee, epi:UItyt7rFkeOPnI.6KtaclLDviM19Sxa, fn:z42Y/QGo9vUN//syw4WSM7kTKlD.mfC, ar:XMHjFz7piZAIPzA4nNG7YumaOW7BEFe, ar:6lWx3Z7kdt53H0U.oEsv2/Y2zai/VDC, fn:BIEftR0x3pSBQoGJfMqerctd6vykxw6, ar:V83CkKa.mEZI7F4JEs0sI95il5DRAOW, ar:XJWOjKCDEx4eugC9Dt/0P9jYx9Zt6kC, ar:bKFIjh7zd5pF0GR.vrJz9vvNknzLKGi, ar:pW/G7uT3a0khPJWk/AzOieElj4cz2ku, ar:1SOVtYR.EsXlA6DdlIF8jYika3BGaZu, ar:cdiTXqrsbD9bI8aX4qRuiInvdHSwUtC, ar:Eg7xFHXmjE/UJ5URfRXV6YRDAt1VODS, ar:DcIUE5ijDjaMmoh59TJiyafZCvChIji, ar:T3Txy4pcITXm2Q4.MCAjpDynmXQjHQS, fn:b5i1LSfxSbfGsnmEJyZOwTBloH.5eb., ar:5TZm./2SXw01t7xgqse8yet6GH13IZm, ar:vqwhT7l74CGVrQZ3tGYEWDyFj.qJDYu, fn:voswl6jUhRyLDFVazv5g9NXhtV1ItsS
sql: SELECT id, title FROM recipes WHERE is_valid=1 AND (title LIKE '%<dish token>%' OR ...)
sql: SELECT recipe_id,pos,raw,canon,forms,alts,qty,unit FROM ingredients WHERE recipe_id IN (<pool ids>) ORDER BY recipe_id,pos

_state: dish: banana bread | include: - | exclude: - | restrictions: - | max_steps: - | available: - | preferences: - | focus: ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC | last_results: 10_

---

### User
Replace the saffron in the first one

### Bot
SUBSTITUTE 'saffron' in ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC  Banana Banana Bread
ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC has no 'saffron' ingredient line, so there is nothing to substitute.

--- RECEIPT ---
tool: substitute
filters: recipe = ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC (Banana Banana Bread); target = saffron (NO role entry in config/roles.yaml)
dataset: 122,918 valid of 125,164 records (2,246 invalid, excluded)
formula: target located by form-aware matcher (normalize.matcher)
valid = title non-blank AND >=1 clean ingredient line AND >=1 instruction step
duplicates: near-duplicate recipes (same title + ingredients, mostly across sources) are NOT removed; see docs/DATA_AUDIT.md section 4
recipe ids: ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC

_state: dish: banana bread | include: - | exclude: - | restrictions: - | max_steps: - | available: - | preferences: - | focus: ar:kq.naD.8G19M4UU9dVvJgHtpfo.l/eC | last_results: 10_