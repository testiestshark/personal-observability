# Personal Observability

A private, single-user record of one person's health, activity and reflection, gathered from their devices and services so they can be seen side by side.

## Language

### Energy

**Calories eaten**:
The food energy the owner logged in MyFitnessPal for a day, as passed on by Garmin.
_Avoid_: Consumed calories (the storage/Garmin word, not a UI label), intake, food calories

**Active calories**:
Garmin's estimate of the energy spent on movement in a day, excluding resting metabolism.
_Avoid_: Exercise calories, calories burned

**Total calories**:
Garmin's estimate of all energy spent in a day, including resting metabolism. Only complete once the day has ended and the watch has synced.
_Avoid_: Calories burned, TDEE

**Calorie goal**:
The daily food-energy target the owner sets in MyFitnessPal, as it stood on that day. A goal change does not rewrite past days.
_Avoid_: Target, budget, net calorie goal

**Complete day**:
A day that has ended and that Garmin has synced after its end, so its **Total calories** is final.

**Energy balance**:
**Calories eaten** minus **Total calories** for a **Complete day**. A negative value is a deficit. It is undefined for a day that isn't complete.
_Avoid_: Net calories, surplus/deficit (as the term itself)

**MFP link date**:
2026-09-28, the first day MyFitnessPal passed food to Garmin. Before it, no day has **Calories eaten**, and that is expected rather than a gap in logging.
