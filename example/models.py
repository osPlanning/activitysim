import urbansim.sim.simulation as sim
import os
from activitysim import activitysim as asim
from activitysim import omx
from activitysim import skim
import numpy as np
import pandas as pd


@sim.table()
def auto_alts():
    return asim.identity_matrix(["cars%d" % i for i in range(5)])


@sim.table()
def cdap_alts():
    return asim.identity_matrix(["Mandatory", "NonMandatory", "Home"])


@sim.table()
def zones():
    # I grant this is a weird idiom but it helps to name the index
    return pd.DataFrame({"TAZ": np.arange(1454)+1}).set_index("TAZ")


@sim.injectable()
def nonmotskm_omx():
    return omx.open_omxfile('data/nonmotskm.omx')


@sim.injectable()
def distance_matrix(nonmotskm_omx):
    return skim.Skim(nonmotskm_omx['DIST'], offset=-1)


@sim.injectable()
def auto_ownership_spec():
    f = os.path.join('configs', "auto_ownership_coeffs.csv")
    return asim.read_model_spec(f).head(4*26)


@sim.injectable()
def workplace_location_spec():
    f = os.path.join('configs', "workplace_location.csv")
    return asim.read_model_spec(f).head(15)


@sim.table()
def workplace_size_spec():
    f = os.path.join('configs', 'workplace_location_size_terms.csv')
    return pd.read_csv(f)


@sim.injectable()
def cdap_1_person_spec():
    f = os.path.join('configs', 'cdap_1_person.csv')
    return asim.read_model_spec(f)


@sim.injectable()
def cdap_2_person_spec():
    f = os.path.join('configs', 'cdap_2_person.csv')
    return asim.read_model_spec(f)


@sim.table()
def workplace_size_terms(land_use, workplace_size_spec):
    """
    This method takes the land use data and multiplies various columns of the
    land use data by coefficients from the workplace_size_spec table in order
    to yield a size term (a linear combination of land use variables) with
    specified coefficients for different segments (like low, med, and high
    income)
    """
    land_use = land_use.to_frame()

    df = workplace_size_spec.to_frame().query("purpose == 'work'")

    df = df.drop("purpose", axis=1).set_index("segment")

    new_df = {}
    for index, row in df.iterrows():

        missing = row[~row.index.isin(land_use.columns)]

        if len(missing) > 0:
            print "WARNING: missing columns in land use\n", missing.index

        row = row[row.index.isin(land_use.columns)]

        sparse = land_use[list(row.index)]

        new_df["size_"+index] = np.dot(sparse.as_matrix(), row.values)

    new_df = pd.DataFrame(new_df, index=land_use.index)

    return new_df


@sim.model()
def auto_ownership_simulate(households,
                            auto_alts,
                            auto_ownership_spec,
                            land_use,
                            accessibility):

    choosers = sim.merge_tables(households.name, tables=[households,
                                                         land_use,
                                                         accessibility])
    alternatives = auto_alts.to_frame()

    choices, model_design = \
        asim.simple_simulate(choosers, alternatives, auto_ownership_spec,
                             mult_by_alt_col=True)

    # map the string names to actual counts of cars
    choices = choices.map(dict([("cars%d" % i , i) for i in range(5)]))

    print "Choices:\n", choices.value_counts()
    sim.add_column("households", "auto_ownership", choices)

    return model_design


@sim.model()
def workplace_location_simulate(persons,
                                households,
                                zones,
                                workplace_location_spec,
                                distance_matrix,
                                workplace_size_terms):

    choosers = sim.merge_tables(persons.name, tables=[persons, households])
    alternatives = zones.to_frame().join(workplace_size_terms.to_frame())

    skims = {
        "distance": distance_matrix
    }

    choices, model_design = \
        asim.simple_simulate(choosers,
                             alternatives,
                             workplace_location_spec,
                             skims,
                             skim_join_name="TAZ",
                             mult_by_alt_col=False,
                             sample_size=50)

    print "Describe of choices:\n", choices.describe()
    sim.add_column("persons", "workplace_taz", choices)

    return model_design


# this return a variable for households which is the concatenated person type
#  for all persons in that household
@sim.column("households")
def ptype(persons):
    return persons.ptype.astype(str).groupby(persons.household_id).\
        apply(lambda x: x.head(3).sum()).astype('int')


@sim.column("households")
def age(persons):
    return persons.age.groupby(persons.household_id).first()


@sim.column("households")
def sex(persons):
    return persons.SEX.groupby(persons.household_id).first()


@sim.model()
def cdap_simulate(households, accessibility, cdap_alts):

    choosers = sim.merge_tables(households.name, tables=[households,
                                                         accessibility])

    alternatives = cdap_alts.to_frame()

    all_choices = []
    for name, grp in choosers.groupby('PERSONS'):

        print "Running model for household size = {}".format(name)

        # for testing - not all these are implemented yet
        if name != 2:
            print "Skipping", name
            continue

        spec = sim.get_injectable('cdap_{}_person_spec'.format(name))

        print grp.ptype.value_counts()

        choices, model_design = \
            asim.simple_simulate(grp, alternatives, spec, mult_by_alt_col=True)

        all_choices.append(choices)

    all_choices = pd.concat(all_choices)
    print "Choices:\n", all_choices.value_counts()
    sim.add_column("persons", "cdap", all_choices)

    return model_design


@sim.column("land_use")
def total_households(land_use):
    return land_use.local.TOTHH


@sim.column("land_use")
def total_employment(land_use):
    return land_use.local.TOTEMP


@sim.column("land_use")
def total_acres(land_use):
    return land_use.local.TOTACRE


@sim.column("land_use")
def county_id(land_use):
    return land_use.local.COUNTY