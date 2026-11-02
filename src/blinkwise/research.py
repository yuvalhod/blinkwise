"""The evidence behind every number Blinkwise uses.

Each coaching message links back to one of these references so users can see
*why* they're being told something. If you change a threshold, update the
reference (or add one) in the same commit. See docs/SCIENCE.md for discussion,
including where the evidence is weak.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class Reference:
    key: str
    citation: str
    finding: str
    url: str


REFERENCES: Dict[str, Reference] = {r.key: r for r in [
    Reference(
        "patel1991",
        "Patel S, Henderson R, Bradley L, Galloway B, Hunter L. Effect of visual display unit use "
        "on blink rate and tear stability. Optom Vis Sci. 1991;68(11):888-892.",
        "Blink rate fell on average about five-fold during screen use compared with normal "
        "conditions.",
        "https://pubmed.ncbi.nlm.nih.gov/1766652/"),
    Reference(
        "tsubota1993",
        "Tsubota K, Nakamori K. Dry eyes and video display terminals. N Engl J Med. "
        "1993;328(8):584.",
        "Widely cited finding that blink rate drops from roughly 22/min when relaxed to about "
        "7/min while looking at a screen.",
        "https://pubmed.ncbi.nlm.nih.gov/?term=Tsubota+Nakamori+Dry+eyes+and+video+display+terminals"),
    Reference(
        "tsubota1995",
        "Tsubota K, Nakamori K. Effects of ocular surface area and blink rate on tear dynamics. "
        "Arch Ophthalmol. 1995;113(2):155-158.",
        "Looking upward exposes more of the eye's surface and increases tear evaporation; "
        "a lower gaze angle reduces exposure.",
        "https://pubmed.ncbi.nlm.nih.gov/?term=Effects+of+ocular+surface+area+and+blink+rate+on+tear+dynamics"),
    Reference(
        "portello2013",
        "Portello JK, Rosenfield M, Chu CA. Blink rate, incomplete blinks and computer vision "
        "syndrome. Optom Vis Sci. 2013;90(5):482-487.",
        "Eye-strain symptoms correlated with the percentage of incomplete blinks; simply "
        "raising blink rate with a tone did not reduce symptoms. Blink quality matters, not "
        "just quantity.",
        "https://pubmed.ncbi.nlm.nih.gov/?term=Blink+rate,+incomplete+blinks+and+computer+vision+syndrome"),
    Reference(
        "nosch2015",
        "Nosch DS, Foppa C, Toth M, Joos RE. Blink animation software to improve blinking and "
        "dry eye symptoms. Optom Vis Sci. 2015;92(9):e310-e315.",
        "An on-screen blink animation raised blink rate by ~6.8/min and reduced dry-eye "
        "symptoms more than placebo in a 1-week crossover study (n=24).",
        "https://pubmed.ncbi.nlm.nih.gov/26164310/"),
    Reference(
        "talens2023",
        "Talens-Estarelles C, Cervino A, Garcia-Lazaro S, Fogelton A, Sheppard A, Wolffsohn JS. "
        "The effects of breaks on digital eye strain, dry eye and binocular vision: Testing the "
        "20-20-20 rule. Cont Lens Anterior Eye. 2023;46(2):101744.",
        "Webcam-based software giving personalised 20-20-20 break reminders reduced digital eye "
        "strain and dry-eye symptoms over two weeks; the benefit faded one week after the "
        "reminders stopped. Small study (n=29).",
        "https://research.aston.ac.uk/en/publications/the-effects-of-breaks-on-digital-eye-strain-dry-eye-and-binocular/"),
    Reference(
        "galinsky2000",
        "Galinsky TL, Swanson NG, Sauter SL, Hurrell JJ, Schleifer LM. A field study of "
        "supplementary rest breaks for data-entry operators. Ergonomics. 2000;43(5):622-638.",
        "Adding short (5-minute) breaks each hour to conventional breaks reduced eye soreness "
        "and musculoskeletal discomfort without hurting productivity (NIOSH field study).",
        "https://pubmed.ncbi.nlm.nih.gov/?term=field+study+of+supplementary+rest+breaks+for+data-entry+operators"),
    Reference(
        "kim2020",
        "Kim AD, Muntz A, Lee J, Wang MTM, Craig JP. Therapeutic benefits of blinking exercises "
        "in dry eye disease. Cont Lens Anterior Eye. 2020 (epub ahead of print).",
        "A 10-second blinking exercise every 20 minutes for four weeks improved dry-eye symptom "
        "scores in a pilot study.",
        "https://pubmed.ncbi.nlm.nih.gov/?term=Therapeutic+benefits+of+blinking+exercises+in+dry+eye+disease"),
    Reference(
        "aston2025",
        "Optimisation of blinking exercises for dry eye disease. Contact Lens and Anterior Eye "
        "(2025), Wolffsohn JS and colleagues, Aston University.",
        "Fifteen 'close - squeeze - open' cycles three times a day reduced symptoms and the "
        "number of incomplete blinks; benefits faded about two weeks after stopping.",
        "https://research.aston.ac.uk/en/publications/optimisation-of-blinking-exercises-for-dry-eye-disease/"),
    Reference(
        "aoa_ergonomics",
        "American Optometric Association. Computer vision syndrome (digital eye strain) "
        "guidance.",
        "Place the screen about 20-28 inches (50-70 cm) from the eyes, with its centre about "
        "15-20 degrees below eye level. Take regular breaks.",
        "https://www.aoa.org/healthy-eyes/eye-and-vision-conditions/computer-vision-syndrome"),
    Reference(
        "sheppard2018",
        "Sheppard AL, Wolffsohn JS. Digital eye strain: prevalence, measurement and "
        "amelioration. BMJ Open Ophthalmol. 2018;3(1):e000146.",
        "Digital eye strain affects around 50% or more of computer users; reduced and "
        "incomplete blinking are key contributors.",
        "https://pubmed.ncbi.nlm.nih.gov/?term=Digital+eye+strain:+prevalence,+measurement+and+amelioration"),
    Reference(
        "dinges1998",
        "Dinges DF, Grace R. PERCLOS: A valid psychophysiological measure of alertness as "
        "assessed by psychomotor vigilance. US Federal Highway Administration, "
        "FHWA-MCRT-98-006, 1998.",
        "The proportion of time the eyes are at least 80% closed (PERCLOS) tracked lapses of "
        "attention better than other eye and head measures; it is the standard camera-based "
        "drowsiness metric.",
        "https://scholar.google.com/scholar?q=PERCLOS+A+valid+psychophysiological+measure+of+alertness"),
    Reference(
        "soukupova2016",
        "Soukupova T, Cech J. Real-time eye blink detection using facial landmarks. 21st "
        "Computer Vision Winter Workshop, 2016.",
        "The eye aspect ratio (EAR) from facial landmarks is a reliable, scale-invariant signal "
        "for detecting blinks from an ordinary camera.",
        "https://vision.fe.uni-lj.si/cvww2016/proceedings/papers/05.pdf"),
    Reference(
        "he2015",
        "He M, Xiang F, Zeng Y, et al. Effect of time spent outdoors at school on the "
        "development of myopia among children in China: a randomized clinical trial. JAMA. "
        "2015;314(11):1142-1148.",
        "An extra 40 minutes of outdoor activity per school day reduced the 3-year incidence "
        "of myopia (30.4% vs 39.5%).",
        "https://pubmed.ncbi.nlm.nih.gov/?term=Effect+of+Time+Spent+Outdoors+at+School+on+the+Development+of+Myopia"),
]}


# ---------------------------------------------------------------------------
# Reference values (used for display and for default thresholds)
# ---------------------------------------------------------------------------
RELAXED_BLINK_RATE = (15, 20)     # blinks/min, typical at rest / in conversation
SCREEN_BLINK_RATE_TYPICAL = (4, 8)  # what is commonly measured during screen use
RECOMMENDED_DISTANCE_CM = (50, 70)
RECOMMENDED_SCREEN_ANGLE_BELOW_EYE_DEG = (15, 20)
TWENTY_TWENTY_TWENTY = dict(every_min=20, look_ft=20, look_m=6, for_s=20)


def cite(key: str) -> Reference:
    return REFERENCES[key]
