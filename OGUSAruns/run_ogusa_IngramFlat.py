import multiprocessing
from distributed import Client
import os, argparse
import json
import pickle
import time
import importlib.resources
import copy
from pathlib import Path
from taxcalc import Policy, Calculator
from taxcalc.growfactors import GrowFactors
import matplotlib.pyplot as plt
from ogusa.calibrate import Calibration
from ogcore.parameters import Specifications
from ogcore import output_tables as ot
from ogcore import output_plots as op
from ogcore.execute import runner
from ogcore.utils import safe_read_pickle

# Use a custom matplotlib style file for plots
style_file_url = (
    "https://raw.githubusercontent.com/PSLmodels/OG-Core/"
    + "master/ogcore/OGcorePlots.mplstyle"
)
plt.style.use(style_file_url)


def main():
    # Define parameters to use for multiprocessing
    num_workers = min(multiprocessing.cpu_count(), 10)
    client = Client(n_workers=num_workers, threads_per_worker=1)
    print("Number of workers = ", num_workers)

    # Directories to save data
    CUR_DIR = os.path.dirname(os.path.realpath(__file__))
    save_dir = CUR_DIR
    base_dir = os.path.join(save_dir, "OUTPUT_TCJAperm")
    reform_dir = os.path.join(save_dir, "OUTPUT_IngramFlat")
    # Set the directory where the TMD data is stored on your local machine
    tmd_dir = (
        "/Users/richardevans/Docs/Economics/OSE/microsim/" +
        "tax-microdata-benchmarking/tmd/storage/output"
    )

    """
    ------------------------------------------------------------------------
    Run baseline policy
    ------------------------------------------------------------------------
    """
    # Set up baseline parameterization
    p = Specifications(
        baseline=True,
        num_workers=num_workers,
        baseline_dir=base_dir,
        output_base=base_dir,
    )
    # Update parameters for baseline from default json file
    with importlib.resources.open_text(
        "ogusa", "ogusa_default_parameters.json"
    ) as file:
        defaults = json.load(file)
    p.update_specifications(defaults)
    p.tax_func_type = "HSV"
    p.age_specific = False
    # Get a TCJA permanence reform policy JSON file from IngramFlatTax repo
    base_url = (
        "github://OpenSourceEcon:IngramFlatTax@main/json/TCJA_ext.json"
    )
    pol1_dict = Calculator.read_json_param_objects(base_url, None)
    iit_baseline = pol1_dict["policy"]
    c = Calibration(
        p,
        estimate_tax_functions=True,
        iit_baseline=iit_baseline,
        client=client,
        data=Path(os.path.join(tmd_dir, "tmd_jason.csv.gz")),
        weights=Path(os.path.join(tmd_dir, "tmd_weights_jason.csv.gz")),
        gfactors=Path(os.path.join(tmd_dir, "tmd_growfactors_jason.csv")),
        records_start_year=2021,
    )
    d = c.get_dict()
    # # additional parameters to change
    updated_params = {
        "start_year": 2026,
        "RC_TPI": 1e-2,
        "etr_params": d["etr_params"],
        "mtrx_params": d["mtrx_params"],
        "mtry_params": d["mtry_params"],
        "mean_income_data": d["mean_income_data"],
        "frac_tax_payroll": d["frac_tax_payroll"],
    }
    p.update_specifications(updated_params)
    # Run model
    start_time = time.time()
    runner(p, time_path=True, client=client)
    print("run time = ", time.time() - start_time)

    """
    ------------------------------------------------------------------------
    Run reform policy
    ------------------------------------------------------------------------
    """
    # Get an Ingram flat tax reform policy JSON file from IngramFlatTax repo
    reform_url = (
        "github://OpenSourceEcon:IngramFlatTax@main/json/" +
        "Ingram_flat_tcjaperm.json"
    )
    pol2_dict = Calculator.read_json_param_objects(reform_url, None)
    iit_reform2 = pol2_dict["policy"]

    # create new Specifications object for reform simulation
    p2 = copy.deepcopy(p)
    p2.baseline = False
    p2.output_base = reform_dir
    # Use calibration class to estimate reform tax functions from
    # Tax-Calculator, specifying reform for Tax-Calculator in iit_reform
    c2 = Calibration(
        p2,
        iit_reform=iit_reform2,
        estimate_tax_functions=True,
        client=client,
        data=Path(os.path.join(tmd_dir, "tmd_jason.csv.gz")),
        weights=Path(os.path.join(tmd_dir, "tmd_weights_jason.csv.gz")),
        gfactors=Path(os.path.join(tmd_dir, "tmd_growfactors_jason.csv")),
        records_start_year=2021,
    )
    # update tax function parameters in Specifications Object
    d = c2.get_dict()
    # additional parameters to change
    updated_params = {
        "baseline_spending": True,
        "etr_params": d["etr_params"],
        "mtrx_params": d["mtrx_params"],
        "mtry_params": d["mtry_params"],
        "mean_income_data": d["mean_income_data"],
        "frac_tax_payroll": d["frac_tax_payroll"],
    }
    p2.update_specifications(updated_params)
    # Run model
    start_time = time.time()
    runner(p2, time_path=True, client=client)
    print("run time = ", time.time() - start_time)
    client.close()

    """
    ------------------------------------------------------------------------
    Save some results of simulations
    ------------------------------------------------------------------------
    """
    base_tpi = safe_read_pickle(os.path.join(base_dir, "TPI", "TPI_vars.pkl"))
    base_params = safe_read_pickle(os.path.join(base_dir, "model_params.pkl"))
    reform_tpi = safe_read_pickle(
        os.path.join(reform_dir, "TPI", "TPI_vars.pkl")
    )
    reform_params = safe_read_pickle(
        os.path.join(reform_dir, "model_params.pkl")
    )
    ans = ot.macro_table(
        base_tpi,
        base_params,
        reform_tpi=reform_tpi,
        reform_params=reform_params,
        var_list=["Y", "C", "K", "L", "r", "w"],
        output_type="pct_diff",
        num_years=10,
        start_year=base_params.start_year,
    )

    # create plots of output
    op.plot_all(
        base_dir,
        reform_dir,
        os.path.join(save_dir, "Ingram_plots_tables"),
    )
    # Create CSV file with output
    ot.tp_output_dump_table(
        base_params,
        base_tpi,
        reform_params,
        reform_tpi,
        table_format="csv",
        path=os.path.join(
            save_dir,
            "Ingram_plots_tables",
            "macro_time_series_output.csv",
        ),
    )

    print("Percentage changes in aggregates:", ans)
    # save percentage change output to csv file
    ans.to_csv(
        os.path.join(
            save_dir, "Ingram_plots_tables", "Ingram_output.csv"
        )
    )


if __name__ == "__main__":
    # execute only if run as a script
    main()
