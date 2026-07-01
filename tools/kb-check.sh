#!/usr/bin/env bash
# kb-check.sh — verify (and optionally auto-fix) the code pointers in kb/ so they
# keep resolving to real code instead of drifting silently. Handles the 3 pointer
# styles a KB actually uses:
#   A) markdown-link : [text](../rel.ext):LINE       path relative to the note's dir   [must resolve]
#   B) backtick path : `repo/rel.ext:LINE`            path relative to the repo root    [must resolve]
#   C) name-anchored : `name()`:LINE / `Name`:LINE    file = same-line md-link / (basename.ext) hint,
#                                                      else the note's primary file (its first link).
#                                                      The NAME is the anchor; the line is a hint.
#
# Drift test: a C pointer is STALE if the symbol it names is not on the cited line
# (catches the in-range case where code merely moved); A/B are checked for file +
# line-in-range. A name not found anywhere in its file is left unchecked (it's a
# cross-file mention, not a pointer). A/B that don't resolve are hard errors.
#
# Modes:
#   (none)        report only; exit 1 if any A/B pointer is broken
#   --fix         rewrite a drifted :line in place when the named symbol has ONE
#                 unambiguous definition in the file; report the rest
#   --freshness   also flag notes older (git mtime) than the code they cite
#
# Deps: bash, awk, grep, sed, wc, git, realpath. Run from the repo root:
#   bash tools/kb-check.sh [--fix|--freshness]
set -u
kb="kb"
[ -d "$kb" ] || { echo "run from the repo root (no kb/ here)"; exit 0; }
ROOT="$(pwd)"; MODE="${1:-}"
INDEX="$(mktemp)"; RECS="$(mktemp)"; FIXES="$(mktemp)"
trap 'rm -f "$INDEX" "$RECS" "$FIXES" "$FIXES.one"' EXIT
git ls-files >"$INDEX" 2>/dev/null || : >"$INDEX"

# ---- per-note awk pass -> TSV records:  note \t nline \t kind \t file \t cline \t sym \t raw
#      C falls back to the note's primary file ($def). sym = own name (C) / line's idents (A,B).
emit='
function join(d,r,  s,n,a,i,k,o,res){ s=d"/"r; n=split(s,a,"/"); k=0
  for(i=1;i<=n;i++){ if(a[i]==""||a[i]==".")continue; if(a[i]==".."){if(k>0)k--;continue} o[++k]=a[i] }
  res=""; for(i=1;i<=k;i++)res=(res==""?o[i]:res"/"o[i]); return res }
function last(s){ sub(/\([^()]*\)$/,"",s); sub(/.*\./,"",s); return s }
BEGIN{ while((getline l<idx)>0){ b=l; sub(/.*\//,"",b); cnt[b]++; pth[b]=l } }
{
  s=$0
  ids=""; t=s; while(match(t,/`[A-Za-z_][A-Za-z0-9_.]*(\(\))?`/)){ w=substr(t,RSTART,RLENGTH); t=substr(t,RSTART+RLENGTH)
    gsub(/`/,"",w); w=last(w); if(w!="") ids=(ids==""?w:ids","w) }
  ctx=""; if(match(s,/\]\([^)]+\)/)){ c=substr(s,RSTART,RLENGTH); sub(/^\]\(/,"",c); sub(/\)$/,"",c); ctx=join(dir,c) }
  hint=""; if(match(s,/\([A-Za-z0-9_]+\.[A-Za-z0-9_]+\)/)){ h=substr(s,RSTART,RLENGTH); gsub(/[()]/,"",h); if(cnt[h]==1) hint=pth[h] }
  t=s; while(match(t,/\]\([^)]+\.[A-Za-z0-9_]+\):[0-9]+/)){ m=substr(t,RSTART,RLENGTH); t=substr(t,RSTART+RLENGTH)
    rel=m; sub(/^\]\(/,"",rel); sub(/\):[0-9]+$/,"",rel); ln=m; sub(/.*:/,"",ln)
    print FILENAME"\t"FNR"\tA\t"join(dir,rel)"\t"ln"\t"ids"\t"m }
  t=s; while(match(t,/`[A-Za-z0-9_.\/-]+:[0-9]+`/)){ m=substr(t,RSTART,RLENGTH); t=substr(t,RSTART+RLENGTH)
    z=m; gsub(/`/,"",z); p=z; sub(/:[0-9]+$/,"",p); ln=z; sub(/.*:/,"",ln)
    if(p ~ /[\/.]/) print FILENAME"\t"FNR"\tB\t"p"\t"ln"\t"ids"\t"m }
  cf=(ctx!=""?ctx:(hint!=""?hint:def))
  t=s; while(match(t,/`[^`]+`:[0-9]+/)){ m=substr(t,RSTART,RLENGTH); t=substr(t,RSTART+RLENGTH)
    nm=m; sub(/`:[0-9]+$/,"",nm); sub(/^`/,"",nm); ln=m; sub(/.*:/,"",ln)
    print FILENAME"\t"FNR"\tC\t"cf"\t"ln"\t"last(nm)"\t"m }
}'

: >"$RECS"
while IFS= read -r note; do
  [ -n "$note" ] || continue
  ndir="$(dirname "$note")"
  def=""; rel="$(grep -oE '\]\([^)]+\.[A-Za-z0-9_]+\)' "$note" 2>/dev/null | head -1 | sed -E 's/^\]\(//; s/\)$//')"
  if [ -n "$rel" ]; then cand="$(cd "$ndir" && realpath -m "$rel" 2>/dev/null)"; case "$cand" in "$ROOT"/*) [ -f "$cand" ] && def="${cand#"$ROOT"/}";; esac; fi
  if [ -z "$def" ]; then bp="$(grep -oE '`[A-Za-z0-9_./-]+\.[A-Za-z0-9_]+:[0-9]+`' "$note" 2>/dev/null | head -1 | tr -d '`' | sed -E 's/:[0-9]+$//')"
    [ -n "$bp" ] && [ -f "$ROOT/$bp" ] && def="$bp"; fi
  awk -v idx="$INDEX" -v dir="$ndir" -v def="$def" "$emit" "$note" >>"$RECS"
done < <(git ls-files "$kb/*.md" 2>/dev/null || find "$kb" -name '*.md')

# escape a symbol for safe use inside an ERE
esc(){ sed 's/[][(){}.^$*+?\\|/]/\\&/g' <<<"$1"; }
# ---- unambiguous DEFINITION line of a symbol, else nothing. A definition is `name(...)`
#      followed by a body (`{`/`=>`/`async`), or `class/enum/... name` — never a bare call
#      (ends `;`), a `.name(` method call, or a // comment. Empty unless exactly one match.
declln(){ local f="$1" e; e="$(esc "$2")"
  grep -anE "(^|[^A-Za-z0-9_.])${e}[[:space:]]*\([^)]*\)[[:space:]]*((async|sync)\*?[[:space:]]*)?(\{|=>)|(class|enum|mixin|extension|typedef|abstract class)[[:space:]]+${e}([^A-Za-z0-9_]|$)" "$f" 2>/dev/null \
    | grep -vE "//.*${e}" \
    | cut -d: -f1 | sort -un | { mapfile -t L; [ "${#L[@]}" -eq 1 ] && [[ "${L[0]:-}" =~ ^[0-9]+$ ]] && echo "${L[0]}"; }; }

bad=0; ok=0; warn=0; skip=0; fixed=0; probs=""; warns=""
online(){ local e; e="$(esc "$3")"; sed -n "${2}p" "$1" | grep -aqE "(^|[^A-Za-z0-9_])$e([^A-Za-z0-9_]|$)"; }  # <file> <line> <sym>
infile(){ local e; e="$(esc "$2")"; grep -aqE "(^|[^A-Za-z0-9_])$e([^A-Za-z0-9_]|$)" "$1"; }                 # <file> <sym>
while IFS=$'\t' read -r note nl kind file cl sym raw; do
  [ -n "$file" ] || { skip=$((skip+1)); continue; }
  f="$ROOT/$file"
  if [ ! -f "$f" ]; then
    [ "$kind" = "C" ] && { skip=$((skip+1)); continue; }
    probs+="  x $note:$nl   $raw   — no such file: $file"$'\n'; bad=$((bad+1)); continue
  fi
  # a C name not present in the file is a cross-file mention, not a pointer here
  if [ "$kind" = "C" ] && [ -n "$sym" ] && ! infile "$f" "$sym"; then skip=$((skip+1)); continue; fi
  total=$(wc -l <"$f" | tr -d ' '); drift=""
  if [ "$cl" -gt "$total" ]; then drift="line $cl past end of file ($total lines)"
  elif [ "$kind" = "C" ] && [ -n "$sym" ]; then online "$f" "$cl" "$sym" || drift="\`$sym\` not on line $cl (moved)"
  else c="$(sed -n "${cl}p" "$f")"; [ -z "${c//[[:space:]]/}" ] && drift="line $cl is blank (anchor moved)"; fi
  [ -z "$drift" ] && { ok=$((ok+1)); continue; }

  newln=""; [ -n "$sym" ] && newln="$(declln "$f" "${sym%%,*}")"
  if [ -n "$newln" ] && [ "$newln" != "$cl" ]; then
    if [ "$MODE" = "--fix" ]; then printf '%s\t%s\t%s\t%s\n' "$note" "$nl" "$raw" "${raw%:*}:$newln" >>"$FIXES"; fixed=$((fixed+1))
    else warns+="  ~ $note:$nl   $raw   — $drift → looks like :$newln (run --fix)"$'\n'; warn=$((warn+1)); fi
  elif [ "$kind" = "C" ]; then skip=$((skip+1))   # can't relocate a name with no clear definition — advisory only
  else probs+="  x $note:$nl   $raw   — $drift"$'\n'; bad=$((bad+1)); fi
done <"$RECS"

if [ "$MODE" = "--fix" ] && [ -s "$FIXES" ]; then
  for note in $(cut -f1 "$FIXES" | sort -u); do
    awk -F'\t' -v N="$note" '$1==N{print $2"\t"$3"\t"$4}' "$FIXES" >"$FIXES.one"
    awk -v map="$FIXES.one" 'BEGIN{ while((getline l<map)>0){ split(l,a,"\t"); ol[a[1]]=a[2]; nw[a[1]]=a[3] } }
      { if(FNR in ol){ o=ol[FNR]; n=nw[FNR]; i=index($0,o); if(i>0) $0=substr($0,1,i-1) n substr($0,i+length(o)) } print }' \
      "$note" >"$note.tmp" && mv "$note.tmp" "$note"
    awk -F'\t' -v N="$note" '$1==N{print "  ~ fixed "$1"   "$3" → "$4}' "$FIXES"
  done
fi

[ -n "$probs" ] && { echo "BROKEN (explicit-file pointers):"; printf '%s' "$probs"; }
[ -n "$warns" ] && { echo "STALE (name-anchored — fix the line or grep the name):"; printf '%s' "$warns"; }

if [ "$MODE" = "--freshness" ]; then
  echo "freshness (note older than cited code):"
  awk -F'\t' '$4!=""{print $1"\t"$4}' "$RECS" | sort -u | while IFS=$'\t' read -r note file; do
    [ -f "$ROOT/$file" ] || continue
    nt=$(git log -1 --format=%ct -- "$note" 2>/dev/null); [ -n "$nt" ] || continue
    ct=$(git log -1 --format=%ct -- "$file" 2>/dev/null); [ -n "$ct" ] || continue
    [ "$ct" -gt "$nt" ] && echo "  ~ $note  — cites newer $file (re-check)"
  done
fi

echo "kb-check: checked $ok, fixed $fixed, warn $warn, skipped $skip (name-only), broken $bad."
[ "$bad" -eq 0 ] && exit 0 || exit 1
