# COMP-2026-00046/47 data repair: realign a return RR's Client with its parent WR.
# Only touches returns that are NOT done/cancel and have NOTHING encoded, so no
# stock is re-owned by this script.
SP = env['stock.picking']

candidates = SP.search([('return_id', '!=', False),
                        ('state', 'not in', ['done', 'cancel'])])
fixed, skipped = [], []
for rr in candidates:
    wr = rr.return_id
    if rr.partner_id.id == wr.partner_id.id:
        continue
    if rr.move_ids or rr.move_line_ids:
        skipped.append((rr.name, rr.state, rr.partner_id.display_name,
                        wr.name, wr.partner_id.display_name,
                        len(rr.move_line_ids)))
        continue
    old = rr.partner_id.display_name
    vals = {'partner_id': wr.partner_id.id}
    if rr.owner_id.id in (rr.partner_id.id, False):
        vals['owner_id'] = wr.partner_id.id
    rr.with_context(skip_return_owner_guard=True,
                    skip_client_lock_guard=True,
                    skip_return_client_sync=True).write(vals)
    rr.message_post(body=(
        "COMP-2026-00046 data repair: Client realigned from <b>%s</b> to "
        "<b>%s</b> to match the parent %s. The document was empty, so no "
        "stock was re-owned." % (old, wr.partner_id.display_name, wr.name)))
    fixed.append((rr.name, rr.state, old, wr.name, wr.partner_id.display_name))

print("FIXED %d" % len(fixed))
for f in fixed:
    print("   %-11s %-9s %-38s -> %-11s %s" % (f[0], f[1], f[2], f[3], f[4]))
print("SKIPPED %d (lines already encoded - handle on the floor)" % len(skipped))
for s in skipped:
    print("   %-11s %-9s %-28s vs %-11s %-28s (%d line/s)" % s)

env.cr.commit()
print("COMMITTED")
