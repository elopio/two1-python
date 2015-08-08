import base64
import pytest
import hashlib
from two1.bitcoin import crypto, script, txn, utils

# The first key in this list had 10000 satoshis sent to it in block 369023
# Do not remove it.
keys = [(crypto.PrivateKey.from_b58check('5JcjcDkFZ3Dz4RjnK3n9cyLVmNS3FzGdNRtNMGFBfJKgzM8eAhH'),
         crypto.PublicKey(0xe674caf81eb3bb4a97f2acf81b54dc930d9db6a6805fd46ca74ac3ab212c0bbf,
                          0x62164a11e7edaf31fbf24a878087d925303079f2556664f3b32d125f2138cbef)),
        (crypto.PrivateKey.from_b58check('5KK5GkzYJKa7evzYPdvDPmB9XWaKQY9qJS5ouRx4ndBHNHbb2Hq'),
         crypto.PublicKey(0x5866260447c0adfdb26dbe5060a7a298e17d051008ce1677d19fe3d3373284b9,
                          0xc384a3445dd96f96c11d3b33d82083e9ecc27d0abfa9fd433afaa5006186bf61))]

@pytest.mark.parametrize("key", keys)
def test_key_addresses(key):
    private_key, public_key = key
    assert private_key.public_key.point == public_key.point

@pytest.mark.parametrize("message, key, exp_sig", [
    (b"Hello, World!!", keys[0], "G1axea+IdcHXdLH6mO5RLLFpwfLHq0aeCio2IBkntGPrBYKuLybWBoF/ZUivx179qGUU9/1kv9GND9sLvsSBlzw="),
    (b"Hello, World!!!", keys[0], "HF9Q4TQMXGhjPeugn852A1WogZOGx2MOL5eMgHryTdkMZCKmCNzjHk4Lmi+sUWv9ekimLtBSiqkfjmoyUo1qzgM="),
    (b"The dog is brown.", keys[0], "HNiO1y7/h+Y+YfKfmubK40jnwraR3FDA7R3Ne42lML1MfIdcXMNvCrUMsONjDSuOqvft8YmIE8sQ/9S2pb+rL7Y="),
    ])
def test_bitcoin_message_signing(message, key, exp_sig):
    private_key, public_key = key

    sig_b64 = private_key.sign_bitcoin(message)
    assert sig_b64.decode('ascii') == exp_sig

    # Check to make sure the recovered public key is correct
    tmp = base64.b64decode(sig_b64)
    magic = tmp[0]
    sig = crypto.Signature.from_bytes(tmp[1:])
    sig.recovery_id = magic - 27

    # Build the message that was signed
    msg = b"\x18Bitcoin Signed Message:\n" + bytes([len(message)]) + message
    msg_hash = hashlib.sha256(msg).digest()

    derived_public_key = crypto.PublicKey.from_signature(msg_hash, sig)
    assert derived_public_key.verify(msg_hash, sig)
    assert derived_public_key.b58address == public_key.b58address

    print("Verify with bx:")
    print("bx message-validate %s %s '%s'" % (public_key.b58address, sig_b64.decode('ascii'), message.decode('ascii')))
    print()
    
def test_sign_txn():
    # Let's create a txn trying to spend one of Satoshi's coins: block 1
    # We make the (false) assertion that we own the private key (private_key1)
    # and for a raw txn, we put the scriptPubKey associated with that private key
    address1 = keys[0][1].b58address
    address2 = keys[1][1].b58address

    prev_txn = '205607fb482a03600b736fb0c257dfd4faa49e45db3990e2c4994796031eae6e' # Real txn in block 369023 to keys[0]
    prev_txn_hash = bytes.fromhex(prev_txn)
    prev_script_pub_key = script.Script.build_p2pkh(utils.address_to_key_hash(address1)[1])
    txn_input = txn.TransactionInput(prev_txn_hash,
                                     0,
                                     script.Script(""),
                                     0xffffffff)

    # Build the output so that it pays out to address2
    out_script_pub_key = script.Script.build_p2pkh(utils.address_to_key_hash(address2)[1])
    txn_output = txn.TransactionOutput(9000, out_script_pub_key) # 1000 satoshi fee

    # Create the txn
    transaction = txn.Transaction(txn.Transaction.DEFAULT_TRANSACTION_VERSION,
                                  [txn_input],
                                  [txn_output],
                                  0)

    # Now sign input 0 (there is only 1)
    transaction.sign_input(0, txn.Transaction.SIG_HASH_ALL, keys[0][0], prev_script_pub_key)

    # Dump it out as hex
    signed_txn_hex = utils.bytes_to_str(bytes(transaction))

    # The above txn was submitted via bitcoin-cli.
    # See: https://www.blocktrail.com/BTC/tx/695f0b8605cc8a117c3fe5b959e6ee2fabfa49dcc615ac496b5dd114105cd360
    assert signed_txn_hex == "0100000001205607fb482a03600b736fb0c257dfd4faa49e45db3990e2c4994796031eae6e000000008b483045022100ed84be709227397fb1bc13b749f235e1f98f07ef8216f15da79e926b99d2bdeb02206ff39819d91bc81fecd74e59a721a38b00725389abb9cbecb42ad1c939fd8262014104e674caf81eb3bb4a97f2acf81b54dc930d9db6a6805fd46ca74ac3ab212c0bbf62164a11e7edaf31fbf24a878087d925303079f2556664f3b32d125f2138cbefffffffff0128230000000000001976a914f1fd1dc65af03c30fe743ac63cef3a120ffab57d88ac00000000"

    # Try verifying it very manually - pretend we're doing actual stack operations
    stack = []
    # Start by pushing the sigScript and publicKey onto the stack
    stack.append(bytes.fromhex(transaction.inputs[0].script.ast[0][2:]))
    stack.append(bytes.fromhex(transaction.inputs[0].script.ast[1][2:]))

    # OP_DUP
    stack.append(stack[-1])

    # OP_HASH160
    pub_key = crypto.PublicKey.from_bytes(stack.pop())
    hash160 = pub_key.address[1:]

    # OP_EQUALVERIFY - this pub key has to match the one in the previous tx output.
    assert pub_key.b58address == address1

    # OP_CHECKSIG
    # Here we need to restructure the txn
    pub_key_dup = stack.pop()
    script_sig_complete = stack.pop()
    script_sig, hash_code_type = script_sig_complete[:-1], script_sig_complete[-1]

    new_txn_input = txn.TransactionInput(prev_txn_hash,
                                         0,
                                         script.Script.build_p2pkh(hash160),
                                         0xffffffff)

    new_txn = txn.Transaction(txn.Transaction.DEFAULT_TRANSACTION_VERSION,
                              [new_txn_input],
                              [txn_output],
                              0)

    new_txn_bytes = bytes(new_txn)
    

    # Now verify
    sig = crypto.Signature.from_der(script_sig)
    assert pub_key.verify(hashlib.sha256(new_txn_bytes + utils.pack_u32(hash_code_type)).digest(), sig)

    assert not pub_key.verify(utils.dhash(new_txn_bytes), sig)