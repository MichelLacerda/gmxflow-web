"""Form fields and durable config generation from the installed gmxflow package."""

import json
from pathlib import Path

from flask_babel import lazy_gettext as _
from gmxflow.config import GmxFlowConfig

SECTIONS = {
    "project": _("Projeto"),
    "input": _("Arquivos de entrada"),
    "force_field": _("Campo de força"),
    "box": _("Caixa"),
    "solvent": _("Solvente"),
    "simulation": _("Simulação"),
    "mdrun": _("Execução"),
    "pdb2gmx": _("Terminais"),
    "analysis": _("Análise"),
    "plots": _("Gráficos"),
}
HELPS = {
    "input.ligand_kind": _(
        "peptide ou small_molecule; moléculas pequenas exigem arquivos MOL2 e STR."
    ),
    "input.ph": _("pH entre 0 e 14 usado na preparação."),
    "simulation.profile": _(
        "standard para produção; smoke apenas para testar o fluxo."
    ),
    "simulation.production_ns": _("Duração da produção em nanossegundos."),
    "simulation.dt_ps": _("Passo de integração em picossegundos."),
    "mdrun.gpu": _("auto, off ou force."),
    "pdb2gmx.terminal_selections": _(
        "Respostas para terminais, separadas por vírgula; vazio usa a "
        "seleção automática."
    ),
}
LABELS = {
    "project.name": _("Nome do projeto"),
    "project.description": _("Descrição"),
    "input.ligand_kind": _("Tipo de ligante"),
    "input.ligand_resname": _("Nome do resíduo do ligante"),
    "input.ph": _("pH"),
    "force_field.name": _("Campo de força"),
    "force_field.water": _("Modelo de água"),
    "box.type": _("Tipo de caixa"),
    "box.distance_nm": _("Distância até a borda (nm)"),
    "solvent.water_structure": _("Estrutura de água"),
    "solvent.salt_concentration_m": _("Concentração de sal (mol/L)"),
    "solvent.positive_ion": _("Íon positivo"),
    "solvent.negative_ion": _("Íon negativo"),
    "solvent.neutralize": _("Neutralizar carga"),
    "simulation.profile": _("Perfil"),
    "simulation.temperature_k": _("Temperatura (K)"),
    "simulation.pressure_bar": _("Pressão (bar)"),
    "simulation.dt_ps": _("Passo de integração (ps)"),
    "simulation.production_ns": _("Produção (ns)"),
    "simulation.nvt_ps": _("Equilíbrio NVT (ps)"),
    "simulation.npt_ps": _("Equilíbrio NPT (ps)"),
    "mdrun.engine": _("Motor de execução"),
    "mdrun.gpu": _("Uso de GPU"),
    "mdrun.gpu_id": _("Identificador da GPU"),
    "mdrun.ntomp": _("Threads OpenMP"),
    "mdrun.pin": _("Afinidade de threads"),
    "pdb2gmx.terminal_selections": _("Seleções de terminais"),
    "analysis.ligand_chain": _("Cadeia do ligante"),
    "analysis.fit_group": _("Grupo de alinhamento"),
    "analysis.center_group": _("Grupo de centralização"),
    "analysis.output_group": _("Grupo de saída"),
    "analysis.contact_cutoff_nm": _("Distância de contato (nm)"),
    "analysis.interaction_energy": _("Energia de interação"),
    "analysis.sasa": _("Análise SASA"),
    "analysis.catalytic_residues": _("Resíduos catalíticos"),
    "analysis.catalytic_distance_cutoff_nm": _("Distância catalítica (nm)"),
    "plots.receptor_color": _("Cor do receptor"),
    "plots.ligand_color": _("Cor do ligante"),
    "plots.band_window": _("Janela da banda"),
    "plots.band_std": _("Desvio da banda"),
    "plots.raw_alpha": _("Opacidade dos dados crus"),
    "plots.band_alpha": _("Opacidade da banda"),
}
CHOICES = {
    "input.ligand_kind": ["peptide", "small_molecule"],
    "force_field.name": [
        "amber99sb-ildn",
        "amber14sb",
        "amber19sb",
        "charmm27",
        "gromos54a7",
        "oplsaa",
        "charmm36-feb2026_cgenff-5.0",
    ],
    "force_field.water": [
        "spc",
        "spce",
        "tip3p",
        "tip4p",
        "tip4pew",
        "tip5p",
        "tips3p",
        "opc",
        "opc3",
    ],
    "box.type": ["triclinic", "cubic", "dodecahedron", "octahedron"],
    "simulation.profile": ["standard", "smoke"],
    "mdrun.engine": ["auto", "gmx", "gmx_mpi"],
    "mdrun.gpu": ["auto", "off", "force"],
    "mdrun.pin": ["auto", "on", "off"],
}
UPLOADS = {
    "receptor": {
        "field": "input.receptor_pdb",
        "extension": ".pdb",
        "label": _("Receptor PDB"),
    },
    "ligand": {
        "field": "input.ligand_pdb",
        "extension": ".pdb",
        "label": _("Ligante PDB"),
    },
    "mol2": {
        "field": "input.ligand_mol2",
        "extension": ".mol2",
        "label": _("Ligante MOL2"),
    },
    "str": {
        "field": "input.ligand_str",
        "extension": ".str",
        "label": _("Ligante STR"),
    },
}
UPLOAD_PATHS = {upload["field"] for upload in UPLOADS.values()}


def fields(config):
    result = []
    for section, title in SECTIONS.items():
        group = getattr(config, section)
        entries = []
        for key, value in group.model_dump().items():
            full = f"{section}.{key}"
            if full in UPLOAD_PATHS:
                continue
            choices = CHOICES.get(full)
            if choices and value not in choices:
                choices = [value, *choices]
            entries.append(
                {
                    "name": full,
                    "label": LABELS.get(full, key.replace("_", " ").capitalize()),
                    "value": value,
                    "help": HELPS.get(full, ""),
                    "type": "bool"
                    if isinstance(value, bool)
                    else "number"
                    if isinstance(value, (int, float))
                    else "list"
                    if isinstance(value, list)
                    else "text",
                    "step": "any" if isinstance(value, float) else "1",
                    "choices": choices,
                }
            )
        result.append((section, title, entries))
    return result


def from_form(form, current=None):
    data = (current or GmxFlowConfig()).model_dump()
    for section, values in data.items():
        for key, old in values.items():
            full = f"{section}.{key}"
            if full in UPLOAD_PATHS:
                continue
            if isinstance(old, bool):
                values[key] = full in form
            elif full in form:
                raw = form[full].strip()
                if isinstance(old, list):
                    values[key] = [
                        item.strip() for item in raw.split(",") if item.strip()
                    ]
                elif isinstance(old, int):
                    values[key] = int(raw)
                elif isinstance(old, float):
                    values[key] = float(raw)
                else:
                    values[key] = raw
    for full, choices in CHOICES.items():
        section, key = full.split(".")
        if data[section][key] not in choices and (
            current is None
            or data[section][key] != getattr(getattr(current, section), key)
        ):
            raise ValueError(f"{full}: escolha uma das opções disponíveis")
    return GmxFlowConfig.model_validate(data)


def to_toml(config):
    # The upstream serializer does not escape quotes in strings. JSON string
    # literals are valid TOML basic strings and keep the stored data intact.
    chunks = []
    for section, values in config.model_dump().items():
        chunks.append(f"[{section}]")
        for key, value in values.items():
            literal = json.dumps(value, ensure_ascii=False)
            chunks.append(f"{key} = {literal}")
        chunks.append("")
    return "\n".join(chunks)


def project_dir(root, project):
    return Path(root) / str(project.owner_id) / str(project.id)
