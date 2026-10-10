# Personal Observability

A private, single-user record of one person's activity, health and work, gathered
from the providers that already hold it.

## Language

### Training

**Fitness activity**:
One recorded training session from any source, such as a run or a workout.
_Avoid_: Session, exercise (for the whole session)

**Run**:
A running fitness activity, recorded by Garmin.

**Workout**:
A strength-training fitness activity, recorded in Hevy. Strength training is only ever recorded in Hevy.
_Avoid_: Using "workout" for a Garmin run or other non-Hevy activity

**Exercise**:
One movement performed within a workout, such as "Bench Press (Barbell)", identified by its position in the workout.
_Avoid_: Lift, movement

**Set**:
One performance of an exercise: its weight, reps and type, identified by its position within that exercise.

**Superset**:
Two or more consecutive exercises in a workout that share a Hevy `superset_id`. Lettered A, B, C in the order they appear, not by id. The same id either side of another exercise is two supersets, and a lone exercise carrying an id is not one.

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
A **Local day** that has ended and that Garmin has synced after its end, so its **Total calories** is final.

**Energy balance**:
**Calories eaten** minus **Total calories** for a **Complete day**. A negative value is a deficit. It is undefined for a day that isn't complete.
_Avoid_: Net calories, surplus/deficit (as the term itself)

**MFP link date**:
2026-09-28, the first day MyFitnessPal passed food to Garmin. Before it, no day has **Calories eaten**, and that is expected rather than a gap in logging.

### GitHub

**GitHub account**:
One GitHub user the app reads activity for. The owner has two, kept apart everywhere they appear. Each has an owner-chosen label and a **detail level**.
_Avoid_: Connection, installation (the superseded GitHub App wording)

**Contribution**:
One piece of GitHub activity on a **Local day**, of one of four types: commit, pull request opened, pull request review, issue opened. Totals are always called "contributions", never "commits".
_Avoid_: Commit (for a total), event, push

**Unsplit contribution**:
A contribution the account's token cannot see into, such as one in a repository it has no access to. Counted but not typed. For a full-detail account a non-zero count means the token is missing repositories.

**Detail level**:
Per **GitHub account**, `full` or `counts_only`. A `counts_only` account stores nothing but per-type daily counts: no repository names, headlines or repository counts.
_Avoid_: Privacy mode, visibility

### Time

**Local day**:
The `Europe/London` calendar date a record counts towards, taken from when it started, never from when it was created or synced.
