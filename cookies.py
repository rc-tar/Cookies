'''
Shouldn't be any randomness after resume - make sure whoever runs it first notes the PC they use
JSON is very readable - can edit if needed in the save files
Sites I found helpful in the creation of this script:
https://docs.python.org/3/library/ (naturally)
https://deap.readthedocs.io/en/master/tutorials/advanced/checkpoint.html
https://deap.readthedocs.io/en/master/tutorials/basic/part2.html#tool-decoration
https://deap.readthedocs.io/en/master/_modules/deap/tools/mutation.html#mutGaussian
'''

import argparse
import json
import math
import os
from pathlib import Path
import random
import secrets
import sys
import tempfile


GENERATIONS = 30 # change as desired, but decide at start
FORMAT = "recipe-comparison" # lol
VERSION = 1
AUTOSAVE = Path("autosave")


def require(condition, message): # mainly for the JSON validation, happens enough I'll save one line
    if not condition:
        raise ValueError(message)


def finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def normalize(values):
    largest = max(values)
    if largest == 0:
        return None
    scaled = [value / largest for value in values]
    total = math.fsum(scaled)
    return [value / total for value in scaled]


def adjusted_values(base_values, deltas, ingredients):
    return [
        min(ingredient["upper"], max(ingredient["lower"], value + delta))
        for value, delta, ingredient in zip(base_values, deltas, ingredients)
    ]


def add_next_competitor(state):
    generation = len(state["history"]) + 1
    if generation > GENERATIONS:
        return dict(state, pending_id=None)
    base_id = state["winner_id"]
    deltas = state["adjustments"][generation - 1]
    recipe = {
        "id": generation,
        "base_id": base_id,
        "adjustments": deltas,
        "values": adjusted_values(
            state["recipes"][base_id]["values"], deltas, state["ingredients"]
        ),
    }
    return dict(state, recipes=state["recipes"] + [recipe], pending_id=generation)


def new_session(settings, ingredients, seed):
    rng = random.Random(seed)
    initial = [rng.uniform(item["lower"], item["upper"]) for item in ingredients]
    adjustments = [
        [rng.gauss(0.0, item["stddev"]) for item in ingredients]
        for _ in range(GENERATIONS)
    ]
    require( # recommended on the site, y'all better not trigger this
        all(finite_number(delta) for row in adjustments for delta in row),
        "An adjustment overflowed. Use smaller standard deviations.",
    )
    return add_next_competitor({
        "format": FORMAT,
        "version": VERSION,
        "seed": seed,
        "generations": GENERATIONS,
        "settings": settings,
        "ingredients": ingredients,
        "adjustments": adjustments,
        "recipes": [{"id": 0, "base_id": None, "adjustments": None, "values": initial}],
        "history": [], # and it goes on and on and on and on
        "winner_id": 0,
        "pending_id": None,
    })


def select_winner(state, winner_id):
    pending_id = state["pending_id"]
    require(pending_id is not None, "All comparisons are already complete.")
    require(
        type(winner_id) is int and winner_id in (state["winner_id"], pending_id),
        "Choose one of the two displayed recipe IDs.",
    )
    decision = {
        "generation": pending_id,
        "base_id": state["winner_id"],
        "competitor_id": pending_id,
        "winner_id": winner_id,
    }
    return add_next_competitor(dict(
        state, winner_id=winner_id, history=state["history"] + [decision]
    ))


def validate_state(state): # tried to cover everything, shouldn't really be needed but I did have an image get corrupted when I uploaded it to eBay so
    require(isinstance(state, dict), "The save must contain a JSON object.")
    require(state.get("format") == FORMAT, "Not a recipe-comparison save file.")
    require(type(state.get("version")) is int and state["version"] == VERSION,
            "Unsupported save-file version.")
    require(type(state.get("seed")) is int, "Missing or invalid random seed.")
    require(type(state.get("generations")) is int and state["generations"] == GENERATIONS,
            "The save must contain exactly 30 generations.")
    settings = state.get("settings")
    require(isinstance(settings, dict), "Missing recipe settings.")
    for key in ("batch_size", "cook_temperature", "cook_time"):
        require(isinstance(settings.get(key), str) and bool(settings[key].strip()),
                f"Missing or invalid {key}.")
    ingredients = state.get("ingredients")
    require(isinstance(ingredients, list) and bool(ingredients), "Missing ingredients.")
    names = set()
    for item in ingredients:
        require(isinstance(item, dict), "Invalid ingredient entry.")
        name = item.get("name")
        require(isinstance(name, str) and bool(name.strip()), "Invalid ingredient name.") # sometimes copilot autofill does understand the assignment
        require(name.casefold() not in names, "Ingredient names must be unique.")
        names.add(name.casefold())
        for key in ("lower", "upper", "stddev"):
            require(finite_number(item.get(key)), f"Invalid {key} for {name}.")
        require(0 <= item["lower"] <= item["upper"], f"Invalid bounds for {name}.")
        require(item["stddev"] >= 0, f"Negative standard deviation for {name}.")

    def vector(values, label):
        require(isinstance(values, list) and len(values) == len(ingredients),
                f"Wrong ingredient count in {label}.")
        require(all(finite_number(value) for value in values), f"Invalid numbers in {label}.")

    adjustments = state.get("adjustments")
    require(isinstance(adjustments, list) and len(adjustments) == GENERATIONS,
            "Missing generation adjustments.")
    for generation, deltas in enumerate(adjustments, 1):
        vector(deltas, f"generation {generation}")
        require(all(item["stddev"] != 0 or delta == 0
                    for item, delta in zip(ingredients, deltas)),
                "An ingredient with zero standard deviation has a nonzero adjustment.")
    history = state.get("history")
    require(isinstance(history, list) and len(history) <= GENERATIONS, "Invalid history.")
    completed = len(history)
    expected_pending = completed + 1 if completed < GENERATIONS else None
    pending = state.get("pending_id")
    require("pending_id" in state and pending == expected_pending
            and (pending is None or type(pending) is int), "Invalid pending comparison.")
    recipes = state.get("recipes")
    require(isinstance(recipes, list)
            and len(recipes) == 1 + completed + (expected_pending is not None),
            "Missing or extra recipes.")
    for recipe_id, recipe in enumerate(recipes):
        require(isinstance(recipe, dict) and type(recipe.get("id")) is int
                and recipe["id"] == recipe_id, "Invalid recipe ID sequence.")
        values = recipe.get("values")
        vector(values, f"recipe {recipe_id}")
        require(all(item["lower"] <= value <= item["upper"]
                    for value, item in zip(values, ingredients)),
                f"Recipe {recipe_id} is outside its ingredient bounds.")
        require("base_id" in recipe and "adjustments" in recipe, "Missing recipe ancestry.")
        if recipe_id == 0:
            require(recipe["base_id"] is None and recipe["adjustments"] is None,
                    "The initial recipe cannot have a base or adjustments.")
            continue
        base_id = recipe["base_id"]
        require(type(base_id) is int and 0 <= base_id < recipe_id, "Invalid recipe base.")
        vector(recipe["adjustments"], f"recipe {recipe_id} adjustments")
        require(recipe["adjustments"] == adjustments[recipe_id - 1],
                f"Recipe {recipe_id} adjustments do not match its generation.")
        expected = adjusted_values(recipes[base_id]["values"], adjustments[recipe_id - 1], ingredients)
        require(values == expected, f"Recipe {recipe_id} does not match its base plus adjustments.")
    winner = 0
    for generation, decision in enumerate(history, 1):
        require(isinstance(decision, dict), "Invalid history entry.")
        for key in ("generation", "base_id", "competitor_id", "winner_id"):
            require(type(decision.get(key)) is int, f"Invalid history {key}.")
        require(decision["generation"] == generation and decision["competitor_id"] == generation,
                "Invalid comparison sequence.")
        require(decision["base_id"] == winner and recipes[generation]["base_id"] == winner,
                "A competitor was not based on the current winner.")
        require(decision["winner_id"] in (winner, generation), "Invalid comparison winner.")
        winner = decision["winner_id"]
    require(type(state.get("winner_id")) is int and state["winner_id"] == winner,
            "Current winner does not match the history.")
    if pending is not None:
        require(recipes[pending]["base_id"] == winner, "Pending recipe has the wrong base.")


def save_state(state, filename):
    # self-overwriting, just in case we forget to save. I don't want to have to redo a recipe
    path = Path(filename).expanduser()
    payload = json.dumps(state, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix="." + path.name + ".", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_state(filename):
    with Path(filename).expanduser().open(encoding="utf-8") as handle:
        state = json.load(handle)
    validate_state(state)
    return state


def prompt_text(prompt):
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Please enter a value.")


def prompt_number(prompt, minimum=0.0):
    while True:
        try:
            value = float(input(prompt))
            if math.isfinite(value) and value >= minimum:
                return value
        except ValueError:
            pass
        print(f"Enter a finite number greater than or equal to {minimum:g}.")


def prompt_setup():
    while True:
        try:
            count = int(input("Number of ingredients: "))
            if count > 0:
                break
        except ValueError:
            pass
        print("Enter a positive whole number.")
    settings = {
        "batch_size": prompt_text("Batch size (include units, e.g. 1000 g): "),
        "cook_temperature": prompt_text("Cook temperature (include units, e.g. 180 C): "),
        "cook_time": prompt_text("Cook time (include units, e.g. 25 min): "),
    }
    print("\nEnter bounds and standard deviations in raw weight units.")
    ingredients = []
    names = set()
    for index in range(count):
        print(f"\nIngredient {index + 1}/{count}")
        while True:
            name = prompt_text("  Name: ")
            if name.casefold() not in names:
                names.add(name.casefold())
                break
            print("Please use a unique ingredient name.")
        lower = prompt_number("  Lower bound: ")
        upper = prompt_number("  Upper bound: ", minimum=lower)
        stddev = prompt_number("  Standard deviation: ")
        ingredients.append({"name": name, "lower": lower, "upper": upper, "stddev": stddev})
    return settings, ingredients


def display_recipe(state, recipe_id, role):
    recipe = state["recipes"][recipe_id]
    settings = state["settings"]
    print(f"\nRecipe {recipe_id} ({role}) | Batch: {settings['batch_size']} | "
          f"Cook time: {settings['cook_time']} | Cook temp: {settings['cook_temperature']}")
    if recipe["base_id"] is None:
        print("  Base: none (random initialization)")
    else:
        print(f"  Base: recipe {recipe['base_id']} + generation {recipe_id} adjustments")
    proportions = normalize(recipe["values"])
    if proportions is None:
        print("  Cannot normalize: all raw ingredient weights are zero.")
        for item in state["ingredients"]:
            print(f"    {item['name']}: undefined (raw weight 0)")
    else:
        print("  Ingredient proportions (total = 1 before display rounding):")
        for item, proportion in zip(state["ingredients"], proportions):
            print(f"    {item['name']}: {proportion:.10g}")


def display_comparison(state):
    print(f"\n{'=' * 72}\nComparison {state['pending_id']}/{GENERATIONS}")
    display_recipe(state, state["winner_id"], "current winner")
    display_recipe(state, state["pending_id"], "competitor")


def print_history(state):
    print(f"\nCompleted all {GENERATIONS} comparisons. Random seed: {state['seed']}")
    print("Raw bounds, standard deviations, and initialization:")
    for item, value in zip(state["ingredients"], state["recipes"][0]["values"]):
        print(f"  {item['name']}: bounds [{item['lower']!r}, {item['upper']!r}], "
              f"stddev {item['stddev']!r}, initial raw value {value!r}")
    display_recipe(state, 0, "random initialization")
    for decision in state["history"]:
        base_id = decision["base_id"]
        competitor_id = decision["competitor_id"]
        base = state["recipes"][base_id]
        competitor = state["recipes"][competitor_id]
        print(f"\nComparison {decision['generation']}: recipe {base_id} vs recipe "
              f"{competitor_id} -> winner: recipe {decision['winner_id']}")
        print(f"  Recipe {competitor_id} base: recipe {base_id}")
        print("  Raw mutations (Gaussian adjustment, then clipping):")
        for item, before, delta, after in zip(
            state["ingredients"], base["values"], competitor["adjustments"], competitor["values"]
        ):
            changed = after - before
            clipped = " [clipped]" if before + delta != after else ""
            print(f"    {item['name']}: base={before!r}, adjustment={delta!r}, "
                  f"result={after!r}, actual change={changed!r}{clipped}")
        display_recipe(state, base_id, "incumbent in this comparison")
        display_recipe(state, competitor_id, "competitor in this comparison")
    display_recipe(state, state["winner_id"], "final winner")


def ask_winner(state):
    while True:
        choice = input(f"\nWinner [{state['winner_id']} / {state['pending_id']}] "
                       "or 's' to save (Ctrl+C to save and exit): ").strip()
        if choice.lower() == "s":
            filename = prompt_text("Save file name: ")
            try:
                save_state(state, filename)
            except (OSError, ValueError) as error:
                print(f"Error: could not save {filename!r}: {error}", file=sys.stderr)
            else:
                print(f"Saved to {filename!r}. This comparison is still pending.")
            continue
        try:
            winner_id = int(choice)
        except ValueError:
            winner_id = None
        if winner_id in (state["winner_id"], state["pending_id"]):
            return winner_id
        print("Enter one of the two displayed recipe IDs, or 's'.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    start = parser.add_mutually_exclusive_group()
    start.add_argument("--load", metavar="FILE", help="load a save or report a completed run")
    start.add_argument("--seed", type=int, help="random seed for a new run (default: fresh random seed)")
    args = parser.parse_args(argv)
    state = None
    try:
        if args.load is not None:
            try:
                state = load_state(args.load)
            except (OSError, ValueError, RecursionError) as error:
                print(f"Error: could not load {args.load!r}: {error}", file=sys.stderr)
                return 1
            print(f"Loaded {args.load!r}: {len(state['history'])}/{GENERATIONS} comparisons complete.")
        else:
            settings, ingredients = prompt_setup()
            seed = args.seed if args.seed is not None else secrets.randbits(64)
            state = new_session(settings, ingredients, seed)
        print(f"Random seed: {state['seed']}")
        while state["pending_id"] is not None:
            display_comparison(state)
            save_state(state, AUTOSAVE)
            print(f"\nAutosaved to {AUTOSAVE}.")
            state = select_winner(state, ask_winner(state))
            save_state(state, AUTOSAVE)
            print(f"\nCurrent winner: recipe {state['winner_id']}")
        print_history(state)
        return 0
    except (KeyboardInterrupt, EOFError):
        print()
        if state is None:
            print("Setup cancelled; no session was created.")
            return 0
        try:
            save_state(state, AUTOSAVE)
        except (OSError, ValueError) as error:
            print(f"Error: could not save progress: {error}", file=sys.stderr)
            return 1
        print(f'Progress saved. Resume with: python recipe_versions.py --load "{AUTOSAVE}"')
        return 0
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
