# Future Possibilities

Speculative, not scheduled. This is a holding pen for ideas that only become
possible _because_ the data domains in [PRODUCT.md](PRODUCT.md) end up
collected in one place — not committed work, and not sequenced. When an idea
here is ready to become real work, it graduates to [ROADMAP.md](ROADMAP.md) /
[backlog.md](backlog.md) and gets removed from this list.

## Dynamic LinkedIn bio / monthly "what I've been up to"

The raw ingredients already exist once a month of activity data has been
collected: GitHub activity, Strava, computer/screen time, mood/journal
entries, weigh-ins, etc. Rather than manually writing a summary of the last
month for a LinkedIn bio, about-me blurb, or similar, feed the last month's
data into an LLM prompt and have it generate a short human-readable summary
of what was actually engaged with / worked on / trained for.

Doesn't need to be fully automated or continuously live-updating — even a
manually-triggered "summarize last 30 days" prompt run once a month would
deliver most of the value. Automation (e.g. a scheduled job that regenerates
it and surfaces it for review before publishing) is a possible later step,
not a requirement to get value from the idea.

Open questions for whenever this gets picked up:

- Which domains actually produce something worth surfacing publicly (GitHub
  activity is the obvious one; mood/journal entries probably aren't)
- Manual review/edit step before anything goes out, vs. fully trusting the
  LLM output
- Where it lives — a page in this app, a copy-pasteable text block, actual
  API push to LinkedIn
