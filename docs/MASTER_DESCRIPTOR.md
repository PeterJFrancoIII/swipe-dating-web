# Master Descriptor — profile media

**Status:** ACTIVE — source of truth for all future builds  
**Updated:** 2026-08-12  
**Executable constants:** `src/swipe_dating/domain/media_spec.py`  
If this document and the code disagree, **this document wins** and the code must be updated.

This file is the product and engineering descriptor for how profile photos are captured, stored, and shown. Do not invent a different resolution, bit depth, or slot count in a later client, compressor, or template.

## Profile photos

| Constraint | Value | Why this is the cap |
|---|---|---|
| Slot count | **6** | Product: a person can add six photos of themselves |
| Picker | Up to remaining empty slots, one chooser | Never more than 6 total; extra files past the cap are skipped |
| Reorder | Drag, or arrow keys when a photo is focused | No move-up / move-down buttons |
| Stored format | **HEIF** (`image/heic`) | Highest common efficiency still-image family on phones |
| Display format | **AVIF** (HEIF/AV1) with JPEG fallback | Same family; works in Chrome, Firefox, and Safari |
| Bit depth | **8 bits per channel** (24-bit RGB) | Volume-majority phone still pipeline (JPEG / 8-bit panels). 10-bit HEIF/HDR exists on flagships and is not the common standard |
| Max raster | **1080 × 2400** (FHD+) | Dominant smartphone panel class by shipment; long edge **2400 px**, short edge **1080 px**. Do not upscale smaller originals |
| Stored size | **≤ 5 MB** per photo after compress | Product limit; compressor must fit without dropping below 8-bit FHD+ unless the image cannot compress |
| Ingest size | **≤ 40 MB** original | Camera originals may exceed 5 MB; reject above 40 MB before decode |
| Color | Display P3 primaries, sRGB transfer when encoding HEIF | Matches current wide-color phone stills without claiming HDR10 |

### Sources (resolution)

- FHD+ **1080 × 2400** is the workhorse mid-range and premium Android panel class in 2025–2026 mobile testing guidance ([Kobiton, Jan 2026](https://kobiton.com/blog/common-screen-resolutions-for-mobile-testing-in-2026/); [Devzery 2025 resolution guide](https://www.devzery.com/post/complete-guide-screen-resolutions-2025)).
- Industry shipment summaries report **about 60% of 2023 smartphone shipments as FHD+** ([Worldmetrics screen-resolution statistics](https://worldmetrics.org/screen-resolution-statistics/)).
- StatCounter mobile “resolutions” are **CSS viewports**, not physical pixels. July 2026 leaders such as 360×800 and 390×844 map to **~1080×2400** and **~1170×2532** physical panels at 3× ([StatCounter mobile screen resolution](https://gs.statcounter.com/screen-resolution-stats/mobile/worldwide)). The shipment-majority physical cap is FHD+; iPhone 14/15/16-class 1170×2532 is nearby but not the volume standard.

### Sources (bit depth)

- The common phone still and web pipeline remains **8-bit JPEG / 8-bit display**. HEIF’s 10-bit path is real on iPhone and some flagships, but 8-bit is still what most phones capture, store as JPEG, and composite ([DPReview on 8-bit JPEG as the default camera output](https://www.dpreview.com/learn/6184595294/10-bit-stills-a-look-at-raw-log-and-the-future-of-photography); [HEICify 8-bit vs 10-bit](https://www.heicify.com/guides/heic-color-depth-explained)).
- Some 10-bit HEIF files will not display on phones that only decode 8-bit HEIF ([Sony support](https://www.sony.com/electronics/support/articles/00252090)).

## Sharing and preview

- A person must be able to **preview the swipe card others see** (only the fields they chose to show, plus gender). Viewer-relative badges (alignment %, distance) are omitted because they belong to the other person. Sexual preference / Show me never appears on the card.
- A person may **share that card by link**. In this local R&D build the link only resolves while the originating browser session is still in process memory on this server. It is not a public internet identity, not production hosting, and not a claim of real-user delivery.
- Opening a shared link stays **adults-only** (18+, fail closed).

## Profile choices

These selectable lists are source of truth for all future builds. Gender lives in `src/swipe_dating/domain/gender_catalog.py`. Other chips live in `src/swipe_dating/domain/preferences.py`. If this document and the code disagree, **this document wins**.

### Gender catalog (living)

**Last reviewed:** 2026-08-12  
**Stay current:** Re-check the sources below whenever this file or `gender_catalog.py` is edited, and at least once per calendar quarter. Update the reviewed date even if no labels change. Do not invent a shorter He/She/Other list in a later client.

**Self-ID:** multi-select, up to **5**. Always shown on the card.  
**Show me / Sexual preference / Filters:** multi-select, any combination from the same list. Always private. Never shown on the public card. Leave all unchecked to see everyone. Do not offer cis-only matching that hides trans people who selected Man or Woman.

| ID | Label |
|---|---|
| woman | Woman |
| man | Man |
| non_binary | Non-binary |
| cis_woman | Cis woman |
| cis_man | Cis man |
| trans_woman | Trans woman |
| trans_man | Trans man |
| transfeminine | Transfeminine |
| transmasculine | Transmasculine |
| transgender | Transgender |
| agender | Agender |
| androgynous | Androgynous |
| bigender | Bigender |
| genderfluid | Genderfluid |
| genderqueer | Genderqueer |
| gender_nonconforming | Gender nonconforming |
| gender_questioning | Gender questioning |
| neutrois | Neutrois |
| pangender | Pangender |
| polygender | Polygender |
| demiboy | Demiboy |
| demigirl | Demigirl |
| non_binary_woman | Non-binary woman |
| non_binary_man | Non-binary man |
| intersex | Intersex |
| intersex_woman | Intersex woman |
| intersex_man | Intersex man |
| two_spirit | Two-Spirit |
| hijra | Hijra |

**Deliberately excluded** (duplicates or terms GLAAD treats as dated): FTM, MTF, Female to Male, Male to Female, Transsexual*, Transgender Male/Female/Person permutations, Cis Female / Cisgender Female, Neither, Other as a dump bucket.

### Sources (gender)

- GLAAD Transgender Glossary and LGBTQ Glossary ([trans terms](https://glaad.org/reference/trans-terms/); [LGBTQ terms](https://glaad.org/reference/terms/))
- OkCupid 22-gender help list, current Aug 2026 ([Gender and Orientation](https://okcupid-app.zendesk.com/hc/en-us/articles/23546564004507-Gender-and-Orientation-on-OkCupid); [blog, Feb 3, 2026](https://theblog.okcupid.com/okcupids-dating-data-center-e7a98676ed35))
- Bumble primary + detail labels ([Inclusive gender identity options](https://bumble.com/en-us/the-buzz/bumble-gender-options))
- Tinder Man / Woman / Beyond Binary plus granular options ([Gender & Sexual Orientation](https://www.help.tinder.com/hc/en-us/articles/15668360470669-Gender-Sexual-Orientation))
- Hinge base + typeahead, last updated Dec 23, 2025 ([How did Hinge decide which gender options to include?](https://help.hinge.co/hc/en-us/articles/4407404339603-How-did-Hinge-decide-which-gender-options-to-include))

| Field | Options | Visibility |
|---|---|---|
| Gender | The catalog above | Always shown on the person's card when set. No hide toggle. |
| Sexual preference / Show me | The same catalog, any mix | Always private. Changes who they see. Never shown on the public card. No show toggle. |
| Photos | Up to 6, session-only | Optional on the card. Default shown. Hidden photos become a letter. |
| Display name | Free text, 64 characters | Optional on the card. Default shown. Hidden name becomes “Someone”. |
| Age | From the adult-gate date of birth | Optional on the card. Default shown. |
| Pronouns | Free text, 40 characters | Optional on the card. Default shown. |
| About | Free text, 500 characters | Optional on the card. Default shown. |
| Looking for | Immediate intent and relational openness from Filters | Optional on the card. Default shown. |
| Interests | Music, live music, movies, movies & TV, reading, coffee, food, travel, fitness, art, fashion, sports, tech, pets, outdoors, nightlife, wellness, cars, volunteering, museums, trivia, science | Current top **5** favorites. Optional on the card. Default shown. |
| Hobbies | Gym, running, hiking, climbing, yoga, cycling, swimming, camping, cooking, baking, gaming, board games, photography, painting, writing, dancing, concerts, thrifting, gardening, ceramics, markets, fishing | Current top **5** favorites. Optional on the card. Default shown. |
| Personality | Calm, intense, outgoing, introverted, playful, serious, adventurous, homebody, spontaneous, planner, goofy, thoughtful, competitive, easygoing, romantic, independent, affectionate, direct | Current top **5** favorites. Optional on the card. Default shown. |
| In the bedroom | Vanilla, curious, adventurous, sensual, kink, BDSM, dominant, submissive, switch, rope, impact play, role play | Current top **5** favorites. Adults 18+, self-declared. Optional on the card. **Default hidden.** |

Do not add race, ethnicity, skin color, height, or inferred scoring fields. Do not infer consent or privacy defaults from gender. Bedroom tags are never used as ranking weights.

## Non-negotiables

- Photos stay out of the unencrypted local R&D profile file.
- Do not raise the raster or bit-depth cap without updating this descriptor and `media_spec.py` together.
- Do not recreate native iOS/Android clients from this file.
