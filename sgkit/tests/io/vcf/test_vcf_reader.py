from typing import MutableMapping

import numpy as np
import pytest
import xarray as xr
from numpy.testing import assert_allclose, assert_array_equal

from sgkit import load_dataset
from sgkit.io.vcf import partition_into_regions, vcf_to_zarr

from .utils import path_for_test


@pytest.mark.parametrize(
    "is_path",
    [True, False],
)
def test_vcf_to_zarr__small_vcf(shared_datadir, is_path, tmp_path):
    path = path_for_test(shared_datadir, "sample.vcf.gz", is_path)
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    vcf_to_zarr(path, output, chunk_length=5, chunk_width=2)
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert ds.attrs["contigs"] == ["19", "20", "X"]
    assert_array_equal(ds["variant_contig"], [0, 0, 1, 1, 1, 1, 1, 1, 2])
    assert_array_equal(
        ds["variant_position"],
        [111, 112, 14370, 17330, 1110696, 1230237, 1234567, 1235237, 10],
    )
    assert_array_equal(
        ds["variant_allele"],
        [
            ["A", "C", "", ""],
            ["A", "G", "", ""],
            ["G", "A", "", ""],
            ["T", "A", "", ""],
            ["A", "G", "T", ""],
            ["T", "", "", ""],
            ["G", "GA", "GAC", ""],
            ["T", "", "", ""],
            ["AC", "A", "ATG", "C"],
        ],
    )
    assert ds["variant_allele"].dtype == "O"
    assert_array_equal(
        ds["variant_id"],
        [".", ".", "rs6054257", ".", "rs6040355", ".", "microsat1", ".", "rsTest"],
    )
    assert ds["variant_id"].dtype == "O"
    assert_array_equal(
        ds["variant_id_mask"],
        [True, True, False, True, False, True, False, True, False],
    )

    assert_array_equal(ds["sample_id"], ["NA00001", "NA00002", "NA00003"])

    call_genotype = np.array(
        [
            [[0, 0], [0, 0], [0, 1]],
            [[0, 0], [0, 0], [0, 1]],
            [[0, 0], [1, 0], [1, 1]],
            [[0, 0], [0, 1], [0, 0]],
            [[1, 2], [2, 1], [2, 2]],
            [[0, 0], [0, 0], [0, 0]],
            [[0, 1], [0, 2], [-1, -1]],
            [[0, 0], [0, 0], [-1, -1]],
            [[0, -1], [0, 1], [0, 2]],
        ],
        dtype="i1",
    )
    call_genotype_phased = np.array(
        [
            [True, True, False],
            [True, True, False],
            [True, True, False],
            [True, True, False],
            [True, True, False],
            [True, True, False],
            [False, False, False],
            [False, True, False],
            [True, False, True],
        ],
        dtype=bool,
    )
    assert_array_equal(ds["call_genotype"], call_genotype)
    assert_array_equal(ds["call_genotype_mask"], call_genotype < 0)
    assert_array_equal(ds["call_genotype_phased"], call_genotype_phased)


@pytest.mark.parametrize(
    "is_path",
    [True, False],
)
def test_vcf_to_zarr__max_alt_alleles(shared_datadir, is_path, tmp_path):
    path = path_for_test(shared_datadir, "sample.vcf.gz", is_path)
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    vcf_to_zarr(path, output, chunk_length=5, chunk_width=2, max_alt_alleles=1)
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    # extra alt alleles are silently dropped
    assert_array_equal(
        ds["variant_allele"],
        [
            ["A", "C"],
            ["A", "G"],
            ["G", "A"],
            ["T", "A"],
            ["A", "G"],
            ["T", ""],
            ["G", "GA"],
            ["T", ""],
            ["AC", "A"],
        ],
    )


@pytest.mark.parametrize(
    "is_path",
    [True, False],
)
def test_vcf_to_zarr__large_vcf(shared_datadir, is_path, tmp_path):
    path = path_for_test(shared_datadir, "CEUTrio.20.21.gatk3.4.g.vcf.bgz", is_path)
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    vcf_to_zarr(path, output, chunk_length=5_000)
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert ds["sample_id"].shape == (1,)
    assert ds["call_genotype"].shape == (19910, 1, 2)
    assert ds["call_genotype_mask"].shape == (19910, 1, 2)
    assert ds["call_genotype_phased"].shape == (19910, 1)
    assert ds["variant_allele"].shape == (19910, 4)
    assert ds["variant_contig"].shape == (19910,)
    assert ds["variant_id"].shape == (19910,)
    assert ds["variant_id_mask"].shape == (19910,)
    assert ds["variant_position"].shape == (19910,)

    assert ds["variant_allele"].dtype == "O"
    assert ds["variant_id"].dtype == "O"


def test_vcf_to_zarr__plain_vcf_with_no_index(shared_datadir, tmp_path):
    path = path_for_test(
        shared_datadir,
        "mixed.vcf",
    )
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    vcf_to_zarr(path, output, truncate_calls=True)
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]
    assert ds["sample_id"].shape == (3,)


@pytest.mark.parametrize(
    "is_path",
    [True, False],
)
def test_vcf_to_zarr__mutable_mapping(shared_datadir, is_path):
    path = path_for_test(shared_datadir, "CEUTrio.20.21.gatk3.4.g.vcf.bgz", is_path)
    output: MutableMapping[str, bytes] = {}

    vcf_to_zarr(path, output, chunk_length=5_000)
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert ds["sample_id"].shape == (1,)
    assert ds["call_genotype"].shape == (19910, 1, 2)
    assert ds["call_genotype_mask"].shape == (19910, 1, 2)
    assert ds["call_genotype_phased"].shape == (19910, 1)
    assert ds["variant_allele"].shape == (19910, 4)
    assert ds["variant_contig"].shape == (19910,)
    assert ds["variant_id"].shape == (19910,)
    assert ds["variant_id_mask"].shape == (19910,)
    assert ds["variant_position"].shape == (19910,)

    assert ds["variant_allele"].dtype == "O"
    assert ds["variant_id"].dtype == "O"


@pytest.mark.parametrize(
    "is_path",
    [True, False],
)
def test_vcf_to_zarr__parallel(shared_datadir, is_path, tmp_path):
    path = path_for_test(shared_datadir, "CEUTrio.20.21.gatk3.4.g.vcf.bgz", is_path)
    output = tmp_path.joinpath("vcf_concat.zarr").as_posix()
    regions = ["20", "21"]

    vcf_to_zarr(path, output, regions=regions, chunk_length=5_000)
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert ds["sample_id"].shape == (1,)
    assert ds["call_genotype"].shape == (19910, 1, 2)
    assert ds["call_genotype_mask"].shape == (19910, 1, 2)
    assert ds["call_genotype_phased"].shape == (19910, 1)
    assert ds["variant_allele"].shape == (19910, 4)
    assert ds["variant_contig"].shape == (19910,)
    assert ds["variant_id"].shape == (19910,)
    assert ds["variant_id_mask"].shape == (19910,)
    assert ds["variant_position"].shape == (19910,)

    assert ds["variant_allele"].dtype == "S48"
    assert ds["variant_id"].dtype == "S1"


@pytest.mark.parametrize(
    "is_path",
    [False],
)
def test_vcf_to_zarr__parallel_temp_chunk_length(shared_datadir, is_path, tmp_path):
    path = path_for_test(shared_datadir, "CEUTrio.20.21.gatk3.4.g.vcf.bgz", is_path)
    output = tmp_path.joinpath("vcf_concat.zarr").as_posix()
    regions = ["20", "21"]

    # Use a temp_chunk_length that is smaller than chunk_length
    vcf_to_zarr(
        path, output, regions=regions, chunk_length=5_000, temp_chunk_length=2_500
    )
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert ds["sample_id"].shape == (1,)
    assert ds["call_genotype"].shape == (19910, 1, 2)
    assert ds["call_genotype_mask"].shape == (19910, 1, 2)
    assert ds["call_genotype_phased"].shape == (19910, 1)
    assert ds["variant_allele"].shape == (19910, 4)
    assert ds["variant_contig"].shape == (19910,)
    assert ds["variant_id"].shape == (19910,)
    assert ds["variant_id_mask"].shape == (19910,)
    assert ds["variant_position"].shape == (19910,)

    assert ds["variant_allele"].dtype == "S48"
    assert ds["variant_id"].dtype == "S1"


def test_vcf_to_zarr__parallel_temp_chunk_length_not_divisible(
    shared_datadir, tmp_path
):
    path = path_for_test(shared_datadir, "CEUTrio.20.21.gatk3.4.g.vcf.bgz", False)
    output = tmp_path.joinpath("vcf_concat.zarr").as_posix()
    regions = ["20", "21"]

    with pytest.raises(
        ValueError,
        match=r"Temporary chunk length in variant dimension \(4000\) must evenly divide target chunk length 5000",
    ):
        # Use a temp_chunk_length that does not divide into chunk_length
        vcf_to_zarr(
            path, output, regions=regions, chunk_length=5_000, temp_chunk_length=4_000
        )


@pytest.mark.parametrize(
    "is_path",
    [True, False],
)
def test_vcf_to_zarr__parallel_partitioned(shared_datadir, is_path, tmp_path):
    path = path_for_test(
        shared_datadir,
        "1000G.phase3.broad.withGenotypes.chr20.10100000.vcf.gz",
        is_path,
    )
    output = tmp_path.joinpath("vcf_concat.zarr").as_posix()

    regions = partition_into_regions(path, num_parts=4)

    vcf_to_zarr(path, output, regions=regions, chunk_length=1_000, chunk_width=1_000)
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert ds["sample_id"].shape == (2535,)
    assert ds["variant_id"].shape == (1406,)


@pytest.mark.parametrize(
    "is_path",
    [True, False],
)
def test_vcf_to_zarr__parallel_partitioned_by_size(shared_datadir, is_path, tmp_path):
    path = path_for_test(
        shared_datadir,
        "1000G.phase3.broad.withGenotypes.chr20.10100000.vcf.gz",
        is_path,
    )
    output = tmp_path.joinpath("vcf_concat.zarr").as_posix()

    vcf_to_zarr(
        path, output, target_part_size="4MB", chunk_length=1_000, chunk_width=1_000
    )
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert ds["sample_id"].shape == (2535,)
    assert ds["variant_id"].shape == (1406,)


@pytest.mark.parametrize(
    "is_path",
    [True, False],
)
def test_vcf_to_zarr__multiple(shared_datadir, is_path, tmp_path):
    paths = [
        path_for_test(shared_datadir, "CEUTrio.20.gatk3.4.g.vcf.bgz", is_path),
        path_for_test(shared_datadir, "CEUTrio.21.gatk3.4.g.vcf.bgz", is_path),
    ]
    output = tmp_path.joinpath("vcf_concat.zarr").as_posix()

    vcf_to_zarr(paths, output, target_part_size=None, chunk_length=5_000)
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert ds["sample_id"].shape == (1,)
    assert ds["call_genotype"].shape == (19910, 1, 2)
    assert ds["call_genotype_mask"].shape == (19910, 1, 2)
    assert ds["call_genotype_phased"].shape == (19910, 1)
    assert ds["variant_allele"].shape == (19910, 4)
    assert ds["variant_contig"].shape == (19910,)
    assert ds["variant_id"].shape == (19910,)
    assert ds["variant_id_mask"].shape == (19910,)
    assert ds["variant_position"].shape == (19910,)

    assert ds.chunks["variants"] == (5000, 5000, 5000, 4910)


@pytest.mark.parametrize(
    "is_path",
    [True, False],
)
def test_vcf_to_zarr__multiple_partitioned(shared_datadir, is_path, tmp_path):
    paths = [
        path_for_test(shared_datadir, "CEUTrio.20.gatk3.4.g.vcf.bgz", is_path),
        path_for_test(shared_datadir, "CEUTrio.21.gatk3.4.g.vcf.bgz", is_path),
    ]
    output = tmp_path.joinpath("vcf_concat.zarr").as_posix()

    regions = [partition_into_regions(path, num_parts=2) for path in paths]

    vcf_to_zarr(paths, output, regions=regions, chunk_length=5_000)
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert ds["sample_id"].shape == (1,)
    assert ds["call_genotype"].shape == (19910, 1, 2)
    assert ds["call_genotype_mask"].shape == (19910, 1, 2)
    assert ds["call_genotype_phased"].shape == (19910, 1)
    assert ds["variant_allele"].shape == (19910, 4)
    assert ds["variant_contig"].shape == (19910,)
    assert ds["variant_id"].shape == (19910,)
    assert ds["variant_id_mask"].shape == (19910,)
    assert ds["variant_position"].shape == (19910,)

    assert ds.chunks["variants"] == (5000, 5000, 5000, 4910)


@pytest.mark.parametrize(
    "is_path",
    [True, False],
)
def test_vcf_to_zarr__multiple_partitioned_by_size(shared_datadir, is_path, tmp_path):
    paths = [
        path_for_test(shared_datadir, "CEUTrio.20.gatk3.4.g.vcf.bgz", is_path),
        path_for_test(shared_datadir, "CEUTrio.21.gatk3.4.g.vcf.bgz", is_path),
    ]
    output = tmp_path.joinpath("vcf_concat.zarr").as_posix()

    vcf_to_zarr(paths, output, target_part_size="40KB", chunk_length=5_000)
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert ds["sample_id"].shape == (1,)
    assert ds["call_genotype"].shape == (19910, 1, 2)
    assert ds["call_genotype_mask"].shape == (19910, 1, 2)
    assert ds["call_genotype_phased"].shape == (19910, 1)
    assert ds["variant_allele"].shape == (19910, 4)
    assert ds["variant_contig"].shape == (19910,)
    assert ds["variant_id"].shape == (19910,)
    assert ds["variant_id_mask"].shape == (19910,)
    assert ds["variant_position"].shape == (19910,)

    assert ds.chunks["variants"] == (5000, 5000, 5000, 4910)


@pytest.mark.parametrize(
    "is_path",
    [True, False],
)
def test_vcf_to_zarr__mutiple_partitioned_invalid_regions(
    shared_datadir, is_path, tmp_path
):
    paths = [
        path_for_test(shared_datadir, "CEUTrio.20.gatk3.4.g.vcf.bgz", is_path),
        path_for_test(shared_datadir, "CEUTrio.21.gatk3.4.g.vcf.bgz", is_path),
    ]
    output = tmp_path.joinpath("vcf_concat.zarr").as_posix()

    # invalid regions, should be a sequence of sequences
    regions = partition_into_regions(paths[0], num_parts=2)

    with pytest.raises(
        ValueError,
        match=r"multiple input regions must be a sequence of sequence of strings",
    ):
        vcf_to_zarr(paths, output, regions=regions, chunk_length=5_000)


@pytest.mark.parametrize(
    "ploidy,mixed_ploidy,truncate_calls,regions",
    [
        (2, False, True, None),
        (4, False, False, None),
        (4, False, False, ["CHR1:0-5", "CHR1:5-10"]),
        (4, True, False, None),
        (4, True, False, ["CHR1:0-5", "CHR1:5-10"]),
        (5, True, False, None),
    ],
)
def test_vcf_to_zarr__mixed_ploidy_vcf(
    shared_datadir, tmp_path, ploidy, mixed_ploidy, truncate_calls, regions
):
    path = path_for_test(shared_datadir, "mixed.vcf.gz")
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    vcf_to_zarr(
        path,
        output,
        regions=regions,
        chunk_length=5,
        chunk_width=2,
        ploidy=ploidy,
        mixed_ploidy=mixed_ploidy,
        truncate_calls=truncate_calls,
    )
    ds = load_dataset(output)

    variant_dtype = "|S1" if regions else "O"
    assert ds.attrs["contigs"] == ["CHR1", "CHR2", "CHR3"]
    assert_array_equal(ds["variant_contig"], [0, 0])
    assert_array_equal(ds["variant_position"], [2, 7])
    assert_array_equal(
        ds["variant_allele"],
        np.array(
            [
                ["A", "T", "", ""],
                ["A", "C", "", ""],
            ],
            dtype=variant_dtype,
        ),
    )
    assert ds["variant_allele"].dtype == variant_dtype
    assert_array_equal(
        ds["variant_id"],
        np.array([".", "."], dtype=variant_dtype),
    )
    assert ds["variant_id"].dtype == variant_dtype
    assert_array_equal(
        ds["variant_id_mask"],
        [True, True],
    )
    assert_array_equal(ds["sample_id"], ["SAMPLE1", "SAMPLE2", "SAMPLE3"])

    assert ds["call_genotype"].attrs["mixed_ploidy"] == mixed_ploidy
    pad = -2 if mixed_ploidy else -1  # -2 indicates a non-allele
    call_genotype = np.array(
        [
            [[0, 0, 1, 1, pad], [0, 0, pad, pad, pad], [0, 0, 0, 1, pad]],
            [[0, 0, 1, 1, pad], [0, 1, pad, pad, pad], [0, 1, -1, -1, pad]],
        ],
        dtype="i1",
    )
    # truncate row vectors if lower ploidy
    call_genotype = call_genotype[:, :, 0:ploidy]

    assert_array_equal(ds["call_genotype"], call_genotype)
    assert_array_equal(ds["call_genotype_mask"], call_genotype < 0)
    if mixed_ploidy:
        assert_array_equal(ds["call_genotype_non_allele"], call_genotype < -1)


@pytest.mark.parametrize(
    "ploidy,mixed_ploidy,truncate_calls",
    [
        (2, False, False),
        (3, True, False),
    ],
)
def test_vcf_to_zarr__mixed_ploidy_vcf_exception(
    shared_datadir, tmp_path, ploidy, mixed_ploidy, truncate_calls
):
    path = path_for_test(shared_datadir, "mixed.vcf.gz")
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    with pytest.raises(ValueError) as excinfo:
        vcf_to_zarr(
            path,
            output,
            ploidy=ploidy,
            mixed_ploidy=mixed_ploidy,
            truncate_calls=truncate_calls,
        )
    assert "Genotype call longer than ploidy." == str(excinfo.value)


def test_vcf_to_zarr__no_genotypes(shared_datadir, tmp_path):
    path = path_for_test(shared_datadir, "no_genotypes.vcf")
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    with pytest.raises(
        ValueError,
        match=r"Genotype information missing from VCF.",
    ):
        vcf_to_zarr(path, output)


def test_vcf_to_zarr__contig_not_defined_in_header(shared_datadir, tmp_path):
    # sample.vcf does not define the contigs in the header, and isn't indexed
    path = path_for_test(shared_datadir, "sample.vcf")
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    with pytest.raises(
        ValueError,
        match=r"Contig '19' is not defined in the header.",
    ):
        vcf_to_zarr(path, output)


def test_vcf_to_zarr__fields(shared_datadir, tmp_path):
    path = path_for_test(shared_datadir, "sample.vcf.gz")
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    vcf_to_zarr(
        path,
        output,
        chunk_length=5,
        chunk_width=2,
        fields=["INFO/DP", "INFO/AA", "INFO/DB", "FORMAT/DP"],
    )
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert_array_equal(ds["variant_DP"], [-1, -1, 14, 11, 10, 13, 9, -1, -1])
    assert ds["variant_DP"].attrs["comment"] == "Total Depth"

    assert_array_equal(ds["variant_AA"], ["", "", "", "", "T", "T", "G", "", ""])
    assert ds["variant_AA"].attrs["comment"] == "Ancestral Allele"

    assert_array_equal(
        ds["variant_DB"], [False, False, True, False, True, False, False, False, False]
    )
    assert ds["variant_DB"].attrs["comment"] == "dbSNP membership, build 129"

    dp = np.array(
        [
            [-1, -1, -1],
            [-1, -1, -1],
            [1, 8, 5],
            [3, 5, 3],
            [6, 0, 4],
            [-1, 4, 2],
            [4, 2, 3],
            [-1, -1, -1],
            [-1, -1, -1],
        ],
        dtype="i4",
    )
    assert_array_equal(ds["call_DP"], dp)
    assert ds["call_DP"].attrs["comment"] == "Read Depth"


def test_vcf_to_zarr__parallel_with_fields(shared_datadir, tmp_path):
    path = path_for_test(shared_datadir, "CEUTrio.20.21.gatk3.4.g.vcf.bgz")
    output = tmp_path.joinpath("vcf.zarr").as_posix()
    regions = ["20", "21"]

    vcf_to_zarr(
        path,
        output,
        regions=regions,
        chunk_length=5_000,
        temp_chunk_length=2_500,
        fields=["INFO/MQ", "FORMAT/PGT"],
    )
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    # select a small region to check
    ds = ds.set_index(variants=("variant_contig", "variant_position")).sel(
        variants=slice((0, 10001661), (0, 10001670))
    )
    assert_allclose(ds["variant_MQ"], [58.33, np.nan, 57.45])
    assert ds["variant_MQ"].attrs["comment"] == "RMS Mapping Quality"

    assert_array_equal(ds["call_PGT"], [[b"0|1"], [b""], [b"0|1"]])
    assert (
        ds["call_PGT"].attrs["comment"]
        == "Physical phasing haplotype information, describing how the alternate alleles are phased in relation to one another"
    )


def test_vcf_to_zarr__field_defs(shared_datadir, tmp_path):
    path = path_for_test(shared_datadir, "sample.vcf.gz")
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    vcf_to_zarr(
        path,
        output,
        fields=["INFO/DP"],
        field_defs={"INFO/DP": {"Description": "Combined depth across samples"}},
    )
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert_array_equal(ds["variant_DP"], [-1, -1, 14, 11, 10, 13, 9, -1, -1])
    assert ds["variant_DP"].attrs["comment"] == "Combined depth across samples"

    vcf_to_zarr(
        path,
        output,
        fields=["INFO/DP"],
        field_defs={"INFO/DP": {"Description": ""}},  # blank description
    )
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert_array_equal(ds["variant_DP"], [-1, -1, 14, 11, 10, 13, 9, -1, -1])
    assert "comment" not in ds["variant_DP"].attrs


def test_vcf_to_zarr__field_number_A(shared_datadir, tmp_path):
    path = path_for_test(shared_datadir, "sample.vcf.gz")
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    vcf_to_zarr(
        path,
        output,
        fields=["INFO/AC"],
        field_defs={"INFO/AC": {"Number": "A"}},
    )
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert_array_equal(
        ds["variant_AC"],
        [
            [-1, -1, -1],
            [-1, -1, -1],
            [-1, -1, -1],
            [-1, -1, -1],
            [-1, -1, -1],
            [-1, -1, -1],
            [3, 1, -1],
            [-1, -1, -1],
            [-1, -1, -1],
        ],
    )
    assert (
        ds["variant_AC"].attrs["comment"]
        == "Allele count in genotypes, for each ALT allele, in the same order as listed"
    )


def test_vcf_to_zarr__field_number_R(shared_datadir, tmp_path):
    path = path_for_test(shared_datadir, "CEUTrio.21.gatk3.4.g.vcf.bgz")
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    vcf_to_zarr(
        path,
        output,
        fields=["FORMAT/AD"],
        field_defs={"FORMAT/AD": {"Number": "R"}},
    )
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    # select a small region to check
    ds = ds.set_index(variants="variant_position").sel(
        variants=slice(10002764, 10002793)
    )

    ad = np.array(
        [
            [[40, 14, 0, -1]],
            [[-1, -1, -1, -1]],
            [[65, 8, 5, 0]],
            [[-1, -1, -1, -1]],
        ],
    )
    assert_array_equal(ds["call_AD"], ad)
    assert (
        ds["call_AD"].attrs["comment"]
        == "Allelic depths for the ref and alt alleles in the order listed"
    )


def test_vcf_to_zarr__field_number_fixed(shared_datadir, tmp_path):
    path = path_for_test(shared_datadir, "sample.vcf.gz")
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    # HQ Number is 2
    vcf_to_zarr(
        path,
        output,
        fields=["FORMAT/HQ"],
        field_defs={"FORMAT/HQ": {"dimension": "haplotypes"}},
    )
    ds = xr.open_zarr(output)  # type: ignore[no-untyped-call]

    assert_array_equal(
        ds["call_HQ"],
        [
            [[10, 15], [10, 10], [3, 3]],
            [[10, 10], [10, 10], [3, 3]],
            [[51, 51], [51, 51], [-1, -1]],
            [[58, 50], [65, 3], [-1, -1]],
            [[23, 27], [18, 2], [-1, -1]],
            [[56, 60], [51, 51], [-1, -1]],
            [[-1, -1], [-1, -1], [-1, -1]],
            [[-1, -1], [-1, -1], [-1, -1]],
            [[-1, -1], [-1, -1], [-1, -1]],
        ],
    )
    assert ds["call_HQ"].attrs["comment"] == "Haplotype Quality"


def test_vcf_to_zarr__fields_errors(shared_datadir, tmp_path):
    path = path_for_test(shared_datadir, "sample.vcf.gz")
    output = tmp_path.joinpath("vcf.zarr").as_posix()

    with pytest.raises(
        ValueError,
        match=r"VCF field must be prefixed with 'INFO/' or 'FORMAT/'",
    ):
        vcf_to_zarr(path, output, fields=["DP"])

    with pytest.raises(
        ValueError,
        match=r"INFO field 'XX' is not defined in the header.",
    ):
        vcf_to_zarr(path, output, fields=["INFO/XX"])

    with pytest.raises(
        ValueError,
        match=r"FORMAT field 'XX' is not defined in the header.",
    ):
        vcf_to_zarr(path, output, fields=["FORMAT/XX"])

    with pytest.raises(
        ValueError,
        match=r"INFO field 'AC' is defined as Number '.', which is not supported.",
    ):
        vcf_to_zarr(path, output, fields=["INFO/AC"])

    with pytest.raises(
        ValueError,
        match=r"FORMAT field 'HQ' is defined as Number '2', but no dimension name is defined in field_defs.",
    ):
        vcf_to_zarr(path, output, fields=["FORMAT/HQ"])

    with pytest.raises(
        ValueError,
        match=r"INFO field 'AN' is defined as Type 'Blah', which is not supported.",
    ):
        vcf_to_zarr(
            path,
            output,
            fields=["INFO/AN"],
            field_defs={"INFO/AN": {"Type": "Blah"}},
        )
