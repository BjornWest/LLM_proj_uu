"""Generate with shared read-only state and optional exhaustive validation."""
import argparse
import json
from pathlib import Path

from environments.website_world.execution_generation import prepare
from environments.website_world.generation_configs import Library, DEFAULT_LIBRARY, unpack, execution_options


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--config', type=Path)
    source.add_argument('--recipe', help='Saved config name, name@version, or full config digest')
    parser.add_argument('--library', type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--validation', choices=('off', 'full'))
    parser.add_argument('--lazy-publication', action=argparse.BooleanOptionalAction, default=None,
                        help='Publish product fulfilment on demand in this fresh execution recipe')
    parser.add_argument('--answer-grading', choices=('off', 'subscription-post-run'))
    parser.add_argument('--extractor-model')
    parser.add_argument('--extractor-effort', choices=('low','medium','high','xhigh','max','ultra'))
    args = parser.parse_args()
    library = Library(args.library)
    source_recipe = library.get(args.recipe) if args.recipe else None
    bundle = unpack(source_recipe if source_recipe is not None else json.loads(args.config.read_text()))
    execution = bundle['execution']
    if args.validation is not None:execution['validation'] = args.validation
    if args.lazy_publication is not None:execution['lazy_publication'] = args.lazy_publication
    if args.answer_grading is not None:
        execution['answer_grading'] = {'mode': args.answer_grading}
    if args.extractor_model is not None or args.extractor_effort is not None:
        if execution['answer_grading']['mode'] == 'off':parser.error('Extractor overrides require answer grading')
        if args.extractor_model is not None:execution['answer_grading']['model'] = args.extractor_model
        if args.extractor_effort is not None:execution['answer_grading']['reasoning_effort'] = args.extractor_effort
    execution = execution_options(execution)
    grading = None if execution['answer_grading']['mode'] == 'off' else execution['answer_grading']
    manifest = prepare(bundle['request'], args.output, validation=execution['validation'],
                       answer_grading=grading, lazy_publication=execution['lazy_publication'])
    if args.recipe:
        # Overrides create a new named version, retaining the effective recipe.
        library.import_generation(args.output,source_recipe['name'],
                                  tags=source_recipe['tags'],notes=source_recipe['notes'],
                                  source_recipe=source_recipe)
    print(json.dumps({'output': str(args.output.resolve()), 'world_id': manifest['world_id'],
                      'summary': manifest['summary'], 'validation': execution['validation'], 'model_runs': 0}))


if __name__ == '__main__':
    main()
