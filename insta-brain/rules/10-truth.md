# Rule 10 — Every fact must be 100% true

## The rule
Every claim that ships under @factjot must be independently verifiable, sourced, and free of "loosely true" embellishment.

## Why
- Once we ship one wrong fact, the brand is dead. Recovery is hard.
- Cold audiences screenshot bad facts. They live forever.
- Toby's voice is dry and precise. Sloppy facts contradict the voice itself.

## How (verification gate)
A candidate fact must satisfy ALL of:
1. **≥ 2 independent reputable sources.** Independent means different domains (NASA + Britannica = ok; two BBC pages = not ok).
2. **Confidence ≥ 0.65** as computed by `src/verification/fact_checker.py::FactVerificationLayer`. Confidence is a weighted average of source-quality scores minus contradiction-flag penalties.
3. **Concrete anchor.** A number, a date, a named entity. The `_has_concrete_anchor` check rejects fluffy "researchers found unexpected behaviour" claims.
4. **No banned hedges.** "Always", "never", "guaranteed", "proven cure" trip a contradiction flag and drop the fact.
5. **No paraphrase that changes the meaning.** If the source says "around 243 days", the slide can say "about 243 days" but not "exactly 243 days".

## Trusted publisher domains (high quality bonus)
`nasa.gov`, `who.int`, `nature.com`, `science.org`, `britannica.com`, `nationalgeographic.com`, `oceana.org`, `noaa.gov`, `museumoflondon.org.uk`, `nhm.ac.uk`, `smithsonianmag.com`, `bbc.com` (curated articles only, not opinion pieces).

## Hand-curated bank
The gold-standard source is `insta-brain/bank/<topic>.md`. Each entry there has been hand-verified by Toby and includes a source URL list. Bank entries are trusted; they still go through the fact_checker for consistency, but they will never fail it.

## When in doubt
Drop the fact. The pipeline doesn't owe Instagram a daily post if the only candidates are uncertain. Better one missed day than one wrong claim.

## Source storage
Every published fact carries its sources in `data/posted.jsonl`. If a viewer DMs asking "where's that from", the answer is one grep away.
