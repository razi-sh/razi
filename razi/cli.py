import sys
import click
from pathlib import Path

from razi.spec.loader import load_spec, SpecLoadError
from razi.spec.validator import validate_spec, SpecValidationError
from razi.compiler.compile import compile_spec, CompileError
from razi.runtime.runtime import execute_run, RunError
from razi.runtime.synthesis import MaxAttemptsExceeded
from razi.replay.replay import execute_replay, ReplayMismatch

@click.group()
@click.version_option(version="1.0.0", prog_name="razi")
def cli():
    """Razi — Deterministic governance harness for AI workflows.

    The model proposes. The harness authorizes."""
    pass

@cli.command()
@click.argument("spec_path", type=click.Path(exists=True))
def validate(spec_path):
    """Validate spec only, no build artifacts."""
    base_dir = Path.cwd()
    try:
        raw_spec = load_spec(spec_path)
        canonical_json, spec_hash = validate_spec(raw_spec, base_dir)
        
        # Template lives on the synth.json operator
        synth_op = next(
            (op for op in raw_spec.get("operators", []) if op.get("type") == "synth.json"),
            None
        )
        template = synth_op.get("template", "") if synth_op else ""
        if template:
            from razi.spec.validator import hash_file
            template_hash = hash_file(base_dir / template)
        else:
            template_hash = "(none)"

        click.echo("Spec valid")
        click.echo(f"Spec hash:     {spec_hash}")
        click.echo(f"Template hash: {template_hash}")
        sys.exit(0)
    except (SpecLoadError, SpecValidationError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

@cli.command()
@click.argument("spec_path", type=click.Path(exists=True))
def build(spec_path):
    """Compile spec to build artifacts."""
    base_dir = Path.cwd()
    try:
        build_dir = compile_spec(spec_path, base_dir)
        click.echo(f"Build successful. Artifacts in: {build_dir}")
        sys.exit(0)
    except (SpecLoadError, SpecValidationError, CompileError) as e:
        click.echo(f"Build error: {e}", err=True)
        sys.exit(2)

@cli.command()
@click.argument("spec_path", type=click.Path(exists=True))
@click.option("--input", "input_file", type=click.Path(exists=True), required=True, help="Path to input JSON")
@click.option("--build", "force_build", is_flag=True, help="Force rebuild before running")
@click.option("--test-mode", is_flag=True, help="Run with local Ollama provider instead of OpenAI")
@click.option("--test-model", type=str, default=None, help="The model to use in test mode (e.g., llama3.1)")
def run(spec_path, input_file, force_build, test_mode, test_model):
    """Run against input (auto-builds if needed)."""
    base_dir = Path.cwd()
    
    try:
        raw_spec = load_spec(spec_path)
        spec_name = raw_spec.get("name")
        build_dir = base_dir / "build" / spec_name
        
        if force_build or not build_dir.exists():
            click.echo("Building spec...")
            build_dir = compile_spec(spec_path, base_dir)
            
        provider = None
        if test_mode:
            try:
                from razi.providers.ollama_provider import OllamaProvider
                provider = OllamaProvider()
                # Store test_model in the provider or we have to pass it to execute_run
                # the architecture expects `model_config` in `synthesize` from the DAG,
                # but for overriding locally we can patch the provider or pass a system env var
            except ImportError as e:
                click.echo(f"Error loading Ollama provider: {e}", err=True)
                sys.exit(3)

            # If user provided a test_model, we can patch the provider
            if test_model:
                provider._test_model = test_model

        click.echo("Executing run...")
        run_dir = execute_run(build_dir, Path(input_file), base_dir, provider=provider)
        click.echo(f"Run successful. Artifacts in: {run_dir}")
        sys.exit(0)
        
    except (SpecLoadError, SpecValidationError, CompileError) as e:
        click.echo(f"Spec/build error: {e}", err=True)
        sys.exit(2)
    except RunError as e:
        click.echo(f"Runtime validation error: {e}", err=True)
        sys.exit(3)
    except MaxAttemptsExceeded as e:
        click.echo(f"Max attempts exceeded: {e}", err=True)
        sys.exit(4)
    except Exception as e:
        # Catch unexpected errors to a generic runtime failure code
        click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(3)

@cli.command()
@click.argument("run_id")
@click.option("--ignore-template-drift", is_flag=True, help="Allow replay even if template file has changed")
def replay(run_id, ignore_template_drift):
    """Replay stored run deterministically."""
    base_dir = Path.cwd()
    run_dir = base_dir / "runs" / run_id
    
    if not run_dir.exists() or not run_dir.is_dir():
        click.echo(f"Replay error: Run directory not found: {run_dir}", err=True)
        sys.exit(5)
        
    try:
        click.echo(f"Replaying run: {run_id} ...")
        report_path = execute_replay(run_dir, base_dir, ignore_template_drift)
        click.echo(f"Replay successful. Report saved to: {report_path}")
        sys.exit(0)
    except ReplayMismatch as e:
        click.echo(f"Replay mismatch: {e}", err=True)
        sys.exit(5)
    except Exception as e:
        click.echo(f"Replay execution error: {e}", err=True)
        sys.exit(5)

if __name__ == "__main__":
    cli()
