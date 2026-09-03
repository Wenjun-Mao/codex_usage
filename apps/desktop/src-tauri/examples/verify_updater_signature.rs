use base64::{engine::general_purpose::STANDARD, Engine as _};
use minisign_verify::{PublicKey, Signature};
use serde_json::Value;
use std::env;
use std::fs::File;
use std::io::{BufReader, Read};
use std::path::Path;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let arguments: Vec<String> = env::args().collect();
    if arguments.len() != 4 {
        return Err(
            "usage: verify_updater_signature <tauri.conf.json> <artifact> <signature>".into(),
        );
    }

    let config: Value = serde_json::from_reader(BufReader::new(File::open(&arguments[1])?))?;
    let encoded_key = config
        .pointer("/plugins/updater/pubkey")
        .and_then(Value::as_str)
        .ok_or("Tauri updater public key is missing")?;
    let public_key = decode_public_key(encoded_key)?;
    let encoded_signature = std::fs::read_to_string(&arguments[3])?;
    let signature = decode_signature(&encoded_signature)?;
    verify_streaming(&public_key, &signature, Path::new(&arguments[2]))?;
    println!("verified updater signature for {}", arguments[2]);
    Ok(())
}

fn decode_public_key(encoded: &str) -> Result<PublicKey, Box<dyn std::error::Error>> {
    let document = String::from_utf8(STANDARD.decode(encoded.trim())?)?;
    Ok(PublicKey::decode(&document)?)
}

fn decode_signature(encoded: &str) -> Result<Signature, Box<dyn std::error::Error>> {
    let document = String::from_utf8(STANDARD.decode(encoded.trim())?)?;
    Ok(Signature::decode(&document)?)
}

fn verify_streaming(
    public_key: &PublicKey,
    signature: &Signature,
    artifact: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut verifier = public_key.verify_stream(signature)?;
    let mut reader = BufReader::new(File::open(artifact)?);
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        verifier.update(&buffer[..read]);
    }
    verifier.finalize()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const PUBLIC_KEY: &str = "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IEFFRDM2N0Q0NjkzRUZBNjUKUldSbCtqNXAxR2ZUcmpkUWtLK1piYkJaVzc5VSthOUlPSmpnd1dCbmJqNDZBWVFHUjN2YWd5Q0UK";
    const SIGNATURE: &str = "dW50cnVzdGVkIGNvbW1lbnQ6IHNpZ25hdHVyZSBmcm9tIHRhdXJpIHNlY3JldCBrZXkKUlVSbCtqNXAxR2ZUcnFEWG1XYk5MUTZZSXBIT0xrSXZHSjZQZGFCcDVqRWlQMUVBQW1OaHN5bU4xRC95ZUpKTC84ZnM2eExLMVhqVlg2UHRjT2xvRjQ2RGZtOEs4Y1dWcEFvPQp0cnVzdGVkIGNvbW1lbnQ6IHRpbWVzdGFtcDoxNzg4NDA3MDI0CWZpbGU6YXJ0aWZhY3QuYmluCkh5VmhVUUFoUkJIUHpXVWowcUtlbjBhWktwd3NBQXQ5SDd0TDFrY2d6Ni9iNG9Za0ljMEtza1ZGVWZRa0ZweCtMU0hMV3JSUmVSbWpMcWxXZ3VsR0JnPT0K";
    const ARTIFACT: &[u8] = b"codex-usage updater verification fixture\n";

    #[test]
    fn tauri_signature_encoding_is_verified_and_tampering_is_rejected() {
        let public_key = decode_public_key(PUBLIC_KEY).expect("public key should decode");
        let signature = decode_signature(SIGNATURE).expect("signature should decode");

        public_key
            .verify(ARTIFACT, &signature, false)
            .expect("fixture signature should verify");
        assert!(public_key
            .verify(
                b"codex-usage updater verification fixture\ntampered",
                &signature,
                false
            )
            .is_err());
    }
}
