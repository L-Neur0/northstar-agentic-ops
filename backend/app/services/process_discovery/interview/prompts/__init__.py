"""Every system prompt sent during the interview, one module per model call (spec 14 §3.9).

ACCEPTED FOR NOW — to be refined with the product owner: the wording of every prompt module here is a first
draft of the prompts and will change after the joint review; the tests hold structure
and required rules, not wording.

Plain functions that render text from data, unit-tested, with no clock, file, network or model
import. Untrusted text (profile values, the expert's messages, document quotes, model-written
reasoning) is always fenced or flattened with `single_line`, never written as instructions.
"""
