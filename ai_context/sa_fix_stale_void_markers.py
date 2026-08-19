# SA "Fix Stale Void Markers" - repairs documents carrying a void flag that
# belongs to a void which no longer exists.
#
# Paste as the body of a NEW Server Action on model stock.picking, run from
# the Actions menu. Restrict it to Inventory Super Admin: it calls
# unvoid_transfer, which refuses to run for anyone else.
#
# It reports two ways. A summary pops up when the action finishes, and every
# document it touched is named in Settings > Technical > Logging (the SA
# `log` helper writes on its own cursor, so those lines survive whatever
# happens to this transaction). It writes nothing to any document's chatter.
#
# ---------------------------------------------------------------------
# WHY THIS EXISTS  (M/WR/08389, MEATS SUPREME, 2026-08-12)
#
# Voiding an RR builds a void WR to reverse it. `button_validate` used to
# auto-void ANY picking carrying `is_void_wr`, with no check that the
# document still reverses a voided parent, while the EDIT guard
# (`_void_mirror_source`) required both the flag AND a resolvable parent.
# An orphaned shell was therefore freely editable AND self-voiding.
#
# Voiding GRJM's M/RR/05176 left unvalidated shells behind. Operators
# repurposed them as blank withdrawal documents for OTHER clients: the
# tracking log on M/WR/08389 shows GRJM's gate pass 113937 and the
# generator's literal loading dock 'N/A' being wiped on 08-12, and MEATS
# SUPREME's own values typed in. On validation the surviving `is_void_wr`
# stamped it VOIDED and archived its PKR row, so 2 pallets / 1,310 kg left
# the warehouse and never reached the client's ledger. Its own tracking
# proves nobody pressed Void: `x_studio_voided` flipped 0 -> 1 in the SAME
# write that set the picking Done.
#
# The code fix is `_apply_void_identity_on_validation` (stock_picking.py),
# which auto-voids only when the void identity holds up. This action cleans
# the records damaged before that fix landed. Upgrade multiple_relocation
# first, or the records this repairs can be damaged again tomorrow.
#
# WHAT IT DOES
#   stale + auto-voided at validation -> unvoid (restores the PKR ledger row
#                                        and recalculates balances), then
#                                        clear the stale flags
#   stale + not voided                -> clear the stale flags only, so the
#                                        document cannot auto-void later
#   stale + voided by a HUMAN         -> reported, never touched. Undoing a
#                                        deliberate void is a business call.
#   identity intact or recoverable    -> left alone entirely
# ---------------------------------------------------------------------

Picking = env['stock.picking']
TrackingValue = env['mail.tracking.value']
Message = env['mail.message']


def voided_at_validation(picking):
    """True when x_studio_voided was stamped in the SAME write that set the
    picking Done. That is the auto-void signature; a deliberate void is a
    separate write, minutes or days later."""
    msgs = Message.search([('model', '=', 'stock.picking'),
                           ('res_id', '=', picking.id)])
    if not msgs:
        return False
    voided_in, done_in = set(), set()
    for tv in TrackingValue.search([('mail_message_id', 'in', msgs.ids)]):
        fname = tv.field_id.name
        if fname == 'x_studio_voided' and tv.new_value_integer:
            voided_in.add(tv.mail_message_id.id)
        elif fname == 'state' and (tv.new_value_char or '') == 'Done':
            done_in.add(tv.mail_message_id.id)
    return bool(voided_in & done_in)


def disarm(picking):
    """Strip the stale void identity, leaving the document as what it is.
    Deliberately silent: nothing is written to the chatter."""
    vals = {'is_void_wr': False, 'is_void_return': False,
            'void_source_picking_id': False}
    if picking.x_studio_source == 'VOIDED':
        vals['x_studio_source'] = False
    if picking.x_studio_manual_document_ == 'VOIDED':
        vals['x_studio_manual_document_'] = False
    if (picking.x_studio_remarks or '').startswith('Auto-created from voided '):
        vals['x_studio_remarks'] = False
    picking.with_context(skip_void_mirror_guard=True).write(vals)


candidates = Picking.search(['|', ('is_void_wr', '=', True),
                             ('is_void_return', '=', True)])

unvoided, disarmed, needs_review = [], [], []
untouched = 0

for pick in candidates:
    status, parent = pick._void_identity_status()
    if status != 'stale':
        untouched += 1
        continue

    if pick.x_studio_voided and pick.state == 'done':
        if not voided_at_validation(pick):
            # Someone voided this on purpose. Restoring its ledger row is a
            # business decision, not a data repair.
            needs_review.append(pick.name)
            continue
        # unvoid_transfer clears x_studio_voided, reactivates the PKR row,
        # repopulates it from the move lines and recalculates the running
        # balances forward. It must run BEFORE the flags are cleared: it
        # refuses to act on a record no longer marked voided.
        pick.unvoid_transfer()
        disarm(pick)
        unvoided.append(pick.name)
    else:
        disarm(pick)
        disarmed.append(pick.name)

log("Fix Stale Void Markers: scanned %d void-flagged picking(s); "
    "%d unvoided + disarmed, %d disarmed only, %d need review, %d left alone."
    % (len(candidates), len(unvoided), len(disarmed), len(needs_review),
       untouched))
for name in unvoided:
    log("  unvoided + disarmed (had auto-voided a real transaction): %s" % name)
for name in disarmed:
    log("  disarmed (stale flag, never voided): %s" % name)
for name in needs_review:
    log("  NEEDS REVIEW (voided deliberately, left untouched): %s" % name,
        level="warning")

summary = [
    "Scanned %d void-flagged transfer(s)." % len(candidates),
    "Unvoided + disarmed: %d%s" % (
        len(unvoided), (" (%s)" % ", ".join(unvoided)) if unvoided else ""),
    "Disarmed only: %d%s" % (
        len(disarmed), (" (%s)" % ", ".join(disarmed)) if disarmed else ""),
    "Left alone (identity intact): %d" % untouched,
]
if needs_review:
    summary.append("NEEDS REVIEW, voided deliberately so not touched: %s"
                   % ", ".join(needs_review))
summary.append("Full detail: Settings > Technical > Logging.")

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': "Fix Stale Void Markers",
        'message': "\n".join(summary),
        'type': 'warning' if needs_review else 'success',
        'sticky': True,
    },
}
