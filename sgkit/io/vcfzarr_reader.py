import tempfile
from pathlib import Path
from typing import Any, Dict, Hashable, List, Optional, Tuple

import dask
import dask.array as da
import xarray as xr
import zarr
from typing_extensions import Literal

from sgkit.io.utils import concatenate_and_rechunk, str_is_int, zarrs_to_dataset

from ..model import DIM_SAMPLE, DIM_VARIANT, create_genotype_call_dataset
from ..typing import ArrayLike, PathType
from ..utils import encode_array, max_str_len


def _ensure_2d(arr: ArrayLike) -> ArrayLike:
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    return arr


def read_vcfzarr(
    path: PathType,
    field_defs: Optional[Dict[str, Dict[str, Any]]] = None,
) -> xr.Dataset:
    """Read a VCF Zarr file created using scikit-allel.

    Loads VCF variant, sample, and genotype data as Dask arrays within a Dataset
    from a Zarr file created using scikit-allel's ``vcf_to_zarr`` function.

    Since ``vcf_to_zarr`` does not preserve phasing information, there is no
    :data:`sgkit.variables.call_genotype_phased_spec` variable in the resulting dataset.

    Parameters
    ----------
    path
        Path to the Zarr file.
    field_defs
        Per-field information that overrides the field definitions in the VCF header, or
        provides extra information needed in the dataset representation. Definitions
        are a represented as a dictionary whose keys are the field names, and values are
        dictionaries with any of the following keys: ``Number``, ``Type``, ``Description``,
        ``dimension``. The first three correspond to VCF header values, and ``dimension`` is
        the name of the final dimension in the array for the case where ``Number`` is a fixed
        integer larger than 1. For example,
        ``{"INFO/AC": {"Number": "A"}, "FORMAT/HQ": {"dimension": "haplotypes"}}``
        overrides the ``INFO/AC`` field to be Number ``A`` (useful if the VCF defines it as
        having variable length with ``.``), and names the final dimension of the ``HQ`` array
        (which is defined as Number 2 in the VCF header) as ``haplotypes``.
        (Note that Number ``A`` is the number of alternate alleles, see section 1.4.2 of the
        VCF spec https://samtools.github.io/hts-specs/VCFv4.3.pdf.)

    Returns
    -------
    A dataset containing the following variables:

    - :data:`sgkit.variables.variant_id_spec` (variants)
    - :data:`sgkit.variables.variant_contig_spec` (variants)
    - :data:`sgkit.variables.variant_position_spec` (variants)
    - :data:`sgkit.variables.variant_allele_spec` (variants)
    - :data:`sgkit.variables.sample_id_spec` (samples)
    - :data:`sgkit.variables.call_genotype_spec` (variants, samples, ploidy)
    - :data:`sgkit.variables.call_genotype_mask_spec` (variants, samples, ploidy)
    """

    vcfzarr = zarr.open_group(str(path), mode="r")

    # don't fix strings since it requires a pass over the whole dataset
    return _vcfzarr_to_dataset(vcfzarr, fix_strings=False, field_defs=field_defs)


def vcfzarr_to_zarr(
    input: PathType,
    output: PathType,
    *,
    contigs: Optional[List[str]] = None,
    grouped_by_contig: bool = False,
    consolidated: bool = False,
    tempdir: Optional[PathType] = None,
    concat_algorithm: Optional[Literal["xarray_internal"]] = None,
) -> None:
    """Convert VCF Zarr files created using scikit-allel to a single Zarr on-disk store in sgkit Xarray format.

    Parameters
    ----------
    input
        Path to the input Zarr file.
    output
        Path to the ouput Zarr file.
    contigs
        The contigs to convert. By default all contigs are converted.
    grouped_by_contig
        Whether there is one group for each contig in the Zarr file, by default False.
    consolidated
        Whether the Zarr file has consolidated metadata, by default False.
    tempdir
        Temporary directory where intermediate files are stored. The default None means
        use the system default temporary directory.
    concat_algorithm
        The algorithm to use to concatenate and rechunk Zarr files. The default None means
        use the optimized version suitable for large files, whereas ``xarray_internal`` will
        use built-in Xarray APIs, which can exhibit high memory usage, see https://github.com/dask/dask/issues/6745.
    """

    if consolidated:
        vcfzarr = zarr.open_consolidated(str(input), mode="r")
    else:
        vcfzarr = zarr.open_group(str(input), mode="r")

    if not grouped_by_contig:
        ds = _vcfzarr_to_dataset(vcfzarr)
        ds.to_zarr(str(output))

    else:
        # read each contig separately, concatenate, rechunk, then save to zarr

        contigs = contigs or list(vcfzarr.group_keys())

        # Index the contig names
        _, variant_contig_names = encode_array(contigs)
        variant_contig_names = list(variant_contig_names)

        vars_to_rechunk = []
        vars_to_copy = []

        with tempfile.TemporaryDirectory(
            prefix="vcfzarr_to_zarr_", suffix=".zarr", dir=tempdir
        ) as tmpdir:
            zarr_files = []
            for i, contig in enumerate(contigs):
                # convert contig group to zarr and save in tmpdir
                ds = _vcfzarr_to_dataset(vcfzarr[contig], contig, variant_contig_names)
                if i == 0:
                    for (var, arr) in ds.data_vars.items():
                        if arr.dims[0] == "variants":
                            vars_to_rechunk.append(var)
                        else:
                            vars_to_copy.append(var)

                contig_zarr_file = Path(tmpdir) / contig
                ds.to_zarr(contig_zarr_file)

                zarr_files.append(str(contig_zarr_file))

            if concat_algorithm == "xarray_internal":
                ds = zarrs_to_dataset(zarr_files)
                ds.to_zarr(output, mode="w")
            else:
                # Use the optimized algorithm in `concatenate_and_rechunk`
                _concat_zarrs_optimized(
                    zarr_files, output, vars_to_rechunk, vars_to_copy
                )


def _vcfzarr_to_dataset(
    vcfzarr: zarr.Array,
    contig: Optional[str] = None,
    variant_contig_names: Optional[List[str]] = None,
    fix_strings: bool = True,
    field_defs: Optional[Dict[str, Dict[str, Any]]] = None,
) -> xr.Dataset:

    variant_position = da.from_zarr(vcfzarr["variants/POS"])

    if contig is None:
        # Get the contigs from variants/CHROM
        variants_chrom = da.from_zarr(vcfzarr["variants/CHROM"]).astype(str)
        variant_contig, variant_contig_names = encode_array(variants_chrom.compute())
        variant_contig = variant_contig.astype("i1")
        variant_contig_names = list(variant_contig_names)
    else:
        # Single contig: contig names were passed in
        assert variant_contig_names is not None
        contig_index = variant_contig_names.index(contig)
        variant_contig = da.full_like(variant_position, contig_index)

    # For variant alleles, combine REF and ALT into a single array
    variants_ref = da.from_zarr(vcfzarr["variants/REF"])
    variants_alt = da.from_zarr(vcfzarr["variants/ALT"])
    variant_allele = da.concatenate(
        [_ensure_2d(variants_ref), _ensure_2d(variants_alt)], axis=1
    )
    # rechunk so there's a single chunk in alleles axis
    variant_allele = variant_allele.rechunk((None, variant_allele.shape[1]))

    if "variants/ID" in vcfzarr:
        variants_id = da.from_zarr(vcfzarr["variants/ID"]).astype(str)
    else:
        variants_id = None

    ds = create_genotype_call_dataset(
        variant_contig_names=variant_contig_names,
        variant_contig=variant_contig,
        variant_position=variant_position,
        variant_allele=variant_allele,
        sample_id=da.from_zarr(vcfzarr["samples"]).astype(str),
        call_genotype=da.from_zarr(vcfzarr["calldata/GT"]),
        variant_id=variants_id,
    )

    # Add a mask for variant ID
    if variants_id is not None:
        ds["variant_id_mask"] = (
            [DIM_VARIANT],
            variants_id == ".",
        )

    # Add any other fields
    field_defs = field_defs or {}
    default_info_fields = ["ALT", "CHROM", "ID", "POS", "REF", "QUAL", "FILTER_PASS"]
    default_format_fields = ["GT"]
    for key in set(vcfzarr["variants"].array_keys()) - set(default_info_fields):
        category = "INFO"
        vcfzarr_key = f"variants/{key}"
        variable_name = f"variant_{key}"
        dims = [DIM_VARIANT]
        field = f"{category}/{key}"
        field_def = field_defs.get(field, {})
        _add_field_to_dataset(
            category, key, vcfzarr_key, variable_name, dims, field_def, vcfzarr, ds
        )
    for key in set(vcfzarr["calldata"].array_keys()) - set(default_format_fields):
        category = "FORMAT"
        vcfzarr_key = f"calldata/{key}"
        variable_name = f"call_{key}"
        dims = [DIM_VARIANT, DIM_SAMPLE]
        field = f"{category}/{key}"
        field_def = field_defs.get(field, {})
        _add_field_to_dataset(
            category, key, vcfzarr_key, variable_name, dims, field_def, vcfzarr, ds
        )

    # Fix string types to include length
    if fix_strings:
        for (var, arr) in ds.data_vars.items():
            kind = arr.dtype.kind
            if kind in ["O", "U", "S"]:
                # Compute fixed-length string dtype for array
                if kind == "O" or var in ("variant_id", "variant_allele"):
                    kind = "S"
                max_len = max_str_len(arr).values  # type: ignore[union-attr]
                dt = f"{kind}{max_len}"
                ds[var] = arr.astype(dt)

                if var in {"variant_id", "variant_allele"}:
                    ds.attrs[f"max_length_{var}"] = max_len

    return ds


def _add_field_to_dataset(
    category: str,
    key: str,
    vcfzarr_key: str,
    variable_name: str,
    dims: List[str],
    field_def: Dict[str, Any],
    vcfzarr: zarr.Array,
    ds: xr.Dataset,
) -> None:
    if "ID" not in vcfzarr[vcfzarr_key].attrs:
        # only convert fields that were defined in the original VCF
        return
    vcf_number = field_def.get("Number", vcfzarr[vcfzarr_key].attrs["Number"])
    dimension, _ = vcf_number_to_dimension_and_size(
        # max_alt_alleles is not relevant since size is not used here
        vcf_number,
        category,
        key,
        field_def,
        max_alt_alleles=0,
    )
    if dimension is not None:
        dims.append(dimension)
    array = da.from_zarr(vcfzarr[vcfzarr_key])
    ds[variable_name] = (dims, array)
    if "Description" in vcfzarr[vcfzarr_key].attrs:
        description = vcfzarr[vcfzarr_key].attrs["Description"]
        if len(description) > 0:
            ds[variable_name].attrs["comment"] = description


def _get_max_len(zarr_groups: List[zarr.Group], attr_name: str) -> int:
    max_len: int = max([group.attrs[attr_name] for group in zarr_groups])
    return max_len


def _concat_zarrs_optimized(
    zarr_files: List[str],
    output: PathType,
    vars_to_rechunk: List[Hashable],
    vars_to_copy: List[Hashable],
) -> None:
    zarr_groups = [zarr.open_group(f) for f in zarr_files]

    first_zarr_group = zarr_groups[0]

    # create the top-level group
    zarr.open_group(str(output), mode="w")

    # copy variables that are to be rechunked
    # NOTE: that this uses _to_zarr function defined here that is needed to avoid
    # race conditions between writing the array contents and its metadata
    # see https://github.com/pystatgen/sgkit/pull/486
    delayed = []  # do all the rechunking operations in one computation
    for var in vars_to_rechunk:
        dtype = None
        if var in {"variant_id", "variant_allele"}:
            max_len = _get_max_len(zarr_groups, f"max_length_{var}")
            dtype = f"S{max_len}"

        arr = concatenate_and_rechunk(
            [group[var] for group in zarr_groups], dtype=dtype
        )
        d = _to_zarr(  # type: ignore[no-untyped-call]
            arr,
            str(output),
            component=var,
            overwrite=True,
            compute=False,
            fill_value=None,
            attrs=first_zarr_group[var].attrs.asdict(),
        )
        delayed.append(d)
    da.compute(*delayed)

    # copy unchanged variables and top-level metadata
    with zarr.open_group(str(output)) as output_zarr:

        # copy variables that are not rechunked (e.g. sample_id)
        for var in vars_to_copy:
            output_zarr[var] = first_zarr_group[var]
            output_zarr[var].attrs.update(first_zarr_group[var].attrs)

        # copy top-level attributes
        output_zarr.attrs.update(first_zarr_group.attrs)


def _to_zarr(  # type: ignore[no-untyped-def]
    arr,
    url,
    component=None,
    storage_options=None,
    overwrite=False,
    compute=True,
    return_stored=False,
    attrs=None,
    **kwargs,
):
    """Extension of dask.array.core.to_zarr that can set attributes on the resulting Zarr array,
    in the same Dask operation.
    """

    # call Dask version with compute=False just to check preconditions
    da.to_zarr(
        arr,
        url,
        component=component,
        storage_options=storage_options,
        overwrite=overwrite,
        compute=False,
        return_stored=return_stored,
        **kwargs,
    )

    storage_options = storage_options or {}
    if isinstance(url, str):
        from dask.bytes.core import get_mapper

        mapper = get_mapper(url, **storage_options)
    else:
        # assume the object passed is already a mapper
        mapper = url  # pragma: no cover
    chunks = [c[0] for c in arr.chunks]
    z = dask.delayed(_zarr_create_with_attrs)(
        shape=arr.shape,
        chunks=chunks,
        dtype=arr.dtype,
        store=mapper,
        path=component,
        overwrite=overwrite,
        attrs=attrs,
        **kwargs,
    )
    return arr.store(z, lock=False, compute=compute, return_stored=return_stored)


def _zarr_create_with_attrs(  # type: ignore[no-untyped-def]
    shape, chunks, dtype, store, path, overwrite, attrs, **kwargs
):
    # Create the zarr group and update its attributes within the same task (thread)
    arr = zarr.create(
        shape=shape,
        chunks=chunks,
        dtype=dtype,
        store=store,
        path=path,
        overwrite=overwrite,
        **kwargs,
    )
    if attrs is not None:
        arr.attrs.update(attrs)
    return arr


def vcf_number_to_dimension_and_size(
    vcf_number: str, category: str, key: str, field_def: Any, max_alt_alleles: int
) -> Tuple[Optional[str], int]:
    if vcf_number in ("0", "1"):
        return (None, 1)
    elif vcf_number == "A":
        return ("alt_alleles", max_alt_alleles)
    elif vcf_number == "R":
        return ("alleles", max_alt_alleles + 1)
    elif str_is_int(vcf_number):
        if "dimension" in field_def:
            dimension = field_def["dimension"]
            return (dimension, int(vcf_number))
        raise ValueError(
            f"{category} field '{key}' is defined as Number '{vcf_number}', but no dimension name is defined in field_defs."
        )
    raise ValueError(
        f"{category} field '{key}' is defined as Number '{vcf_number}', which is not supported."
    )
