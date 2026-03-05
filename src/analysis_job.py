# Runs UX analysis for a specific job
# Called by webapp.py with: python3 src/analysis_job.py <job_id>

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from step2_analysis import run_analysis

if __name__ == "__main__":
    job_id = sys.argv[1]
    run_analysis(flow_id=job_id)