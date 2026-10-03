"""India-focused dashboard visibility, independent of résumé skill coverage."""
from app.discovery.matching import contains

INDIA_LOCATIONS = ("India", "Bengaluru", "Bangalore", "Kolkata", "Hyderabad", "Pune",
                   "Gurugram", "Gurgaon", "Noida", "Chennai", "Mumbai", "Delhi",
                   "Ahmedabad", "Chandigarh", "Kochi", "Coimbatore", "Indore", "Jaipur")


def india_opportunity(job):
    # Generic remote/global is not evidence of India eligibility. Preserve it in history.
    return job.status not in ("Rejected", "Withdrawn") and any(
        contains(job.location or "", location) for location in INDIA_LOCATIONS)
