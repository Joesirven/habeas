"""Local smoke: vector gate used by Spark job (no cluster)."""

from drop_normalize import hash_std, normalize_name


def test_spark_vector_gate():
    fn = hash_std(normalize_name("Danielle"))
    ln = hash_std(normalize_name("Johnson"))
    ndz = hash_std(fn + ln + hash_std("19850704") + hash_std("91790"))
    assert ndz == "PQOfn1RffEKmqMmNAzDKKaoZCwxWbQZkQzPWmQo9REA="
